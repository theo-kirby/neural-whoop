# SIM2REAL.md — closing the gap to a real tiny-whoop

Plan of record for taking neural-whoop policies onto real hardware. Companion to `docs/CONTRACT.md`
(the obs/act/DR seam this leans on). Status: **hardware purchased** — Air65 II bought 2026-07-03;
bring-up starts at Stage 0 when it arrives.

## Locked architecture (decided 2026-06-29 with the user)

| Fork | Choice | Why / implication |
|------|--------|-------------------|
| **Airframe** | **BetaFPV Air65 II** (~17 g racing / 16.6 g champion, 65 mm, 0702SE II 30kKV racing, Matrix G473/ICM42688P, GF 1207 props, analog 5.8G VTX, serial ELRS 2.4) | A true light/twitchy ~17 g tiny-whoop. **Chosen over the same-mass-class Mobula6** (the initial pick) for durability (3-pt FC mount, ~80% less crash damage) + BetaFPV ecosystem, and over the heavier Meteor75. **Forces an airframe-DR re-center** (sim is currently Meteor75-massed). See *Airframe selection* below. |
| **Perception (target_rel)** | **Onboard camera** → offboard gate/blob detector | Real counterpart to the perception oracle (`perception/`). No mocap rig. Analog FPV → host VRX + USB capture; gates need visual markers. |
| **Velocity (vel_body)** | **Optical-flow deck** (PMW3901 + ToF), **fused to velocity on the host** | Betaflight does *not* fuse flow→velocity today (4.6/2025.12 only; INAV/ArduPilot do). Since the policy is offboard, we read raw flow + range and estimate velocity host-side. ~+2 g. |
| **Policy execution** | **Offboard over radio** | Net runs on host, streams CTBR ~100 Hz via MSP (`MSP_SET_RAW_RC`) over ELRS. Matches the Crazyflie sim2real literature and our TorchScript/ONNX export path. Onboard (G473) firmware NN is a later milestone (RAM-tight; Neuroflight needed an H7). |

This is deliberately the **most ambitious corner** of the option space: light airframe + camera perception + flow velocity, skipping the two crutches (mocap, bigger drone) the Crazyflie papers lean on. Staged below so each flight isolates one gap.

## Airframe selection (decided 2026-06-29)

Three 65 mm-class 1S whoops were weighed (Flywheel: airframe-of-record `sparkling-lab-8864`, options `wild-shape-7463` / `black-butterfly-6195`):

- **BetaFPV Air65 II — chosen.** ~17 g, best-reviewed 65 mm whoop, durable 3-pt FC mount (~80% less crash damage — decisive for a crash-heavy autonomous bring-up), BetaFPV/Meteor parts + battery ecosystem.
- **Happymodel Mobula6 2024 V3 — initial pick, superseded.** ~17.6 g, same mass class (so the sim re-center is *identical*); lost on durability + ecosystem, not dynamics.
- **BetaFPV Meteor75 Pro — set aside.** ~31 g; closest to our current sim mass (28–36 g) but the least "true tiny-whoop". Surfaced the finding that our sim is Meteor75-massed.

Because the chosen and runner-up are the same ~17 g class, the dynamics gap below is airframe-switch-invariant.

## The gap: sim today vs. Air65 II (real AUW ~25 g)

Sim values from `dynamics/whoop.py`, `contract.py`, `randomization.py`, `configs/gate_race.yaml`.
**Weight note:** the "~17 g" spec is *dry* (no battery). Real **all-up weight** = ~17 g dry + ~8 g (1S 300 mAh) ≈ **~25 g**, or **~27 g** with the ~2 g flow deck. The sim `mass` is AUW, so that's the number to match.

| Quantity | Sim default / DR | Air65 II reality (AUW) | Action |
|---|---|---|---|
| Mass (AUW) | 32 g, DR **28–36 g** | **~25 g** (27 g w/ flow deck) | Re-center to **~26 g, DR ~22–30 g** (`whoop.py:48`). ~20% lighter — modest, not 2×. |
| Inertia J_xy / J_z | 2.3e-5 / 4.0e-5, ±10% | ~0.8× (mass ~20% lower, same 65 mm geometry) | Scale nominals ~0.8× (`whoop.py:51-52`). |
| Arm length | 32 mm | ~32 mm (65 mm wheelbase ÷ 2) | Already correct; confirm at Stage 0 (`whoop.py:49`). |
| TWR (max thrust) | 4:1 (`max_thrust_normed=4.0`) | ~4–5:1 at ~25 g AUW (0702 30kKV) | Sim is **close**; pin from thrust curve at Stage 0 (`contract.py:96`). |
| Rate-loop `K_angvel` | [16,16,8] fixed | = Betaflight PID tune (unknown) | Measure real rate step-response; this is what `rate_gain_frac` hedges (`whoop.py:67`). |
| Policy/control rate | 50 Hz (dt=0.02) | offboard link ~100 Hz typical | Consider 100 Hz; 50 Hz marginal w/ video round-trip (`whoop.py:62`). |
| **Action latency DR** | **0–1 step (0–20 ms)** | offboard+camera ≈ **40–100 ms** | **Widen to ~0–5 steps (0–100 ms)** — the one clearly-large gap (`randomization.py:56`). |
| Body rates | ±12/±12/±6 rad/s, **linear** | Betaflight nonlinear rate curve | Flatten/calibrate BF rates to linear mapping (`contract.py:98-99`). |
| Detector noise | **off** in gate_race | real gate detector on low-res analog FPV | Turn on + calibrate `DetectorNoise` from real video (`perception/`). |
| **Flow→velocity noise** | none (sim feeds GT vel) | flow dropout over low-texture floor, height-coupling, latency | **New DR seam**: flow-velocity error model (counterpart to `DetectorNoise`). |

Revised headline (after the dry-vs-AUW correction): the **mass gap is modest** (~25 g real vs 32 g sim, ~20%; inertia/TWR scale gently and arm is already right), so the **dominant clearly-wrong gap is the action-latency DR** (0–20 ms vs ~40–100 ms offboard). Final airframe numbers get pinned by weighing the real drone at Stage 0.

## Staged plan (de-risking ladder)

### Stage 0 — Actuation seam bring-up (bench, no perception)
Prove the CTBR seam in isolation. Needs only the drone + USB.
- MSP `MSP_SET_RAW_RC` injection into Betaflight (acro mode); handle the MSP-override/failsafe interaction.
- Calibrate Betaflight rate curve → our linear ±12/±6 rad/s mapping.
- Measure real rate step-response (vs `K_angvel=[16,16,8]`), hover throttle, thrust curve / TWR, mass, inertia.
- **Output:** re-centered Air65 II airframe DR + matched controller constants in `dynamics/whoop.py`.

**Bench ladder complete over the WiFi bridge (2026-07-05, branch B live):** `info` (BTFL
2026.6.0), `latency` (median **2.41 ms**, p99 24 ms — ~100× inside the 300 ms freshness
window), `rc-test` (override seam proven; **MSP_SET_RAW_RC is AETR wire order**, rcData reads
RPYT — see `bench/msp.py`), `motor-test` (indices 0–3 = RR, FR, RL, FL, standard quad-X).
Commits `da0e37a`, `3c5e2bb`. Still open here: rate-curve calibration, step-response/thrust
measurements, and the `msp_override_failsafe` decision.

**d50var_s8 props-off deploy check GREEN (2026-07-07, bench):** selftest parity 4.6e-08;
hand-pose signs correct (tilt-right → roll_us 1178, nose-down → pitch_us 1079); level-still
commanded throttle **1408 ≈ the 1410 µs hover anchor** (the amplitude-DR trim fix, confirmed on
hardware). Two findings: (1) **yaw obs sign REFUTED and fixed** — the clockwise-spin check read
gz *negative* on a CW-from-above spin, so this board's gyro z is inverted vs the textbook BF
convention (same pattern as pitch); `obs_from_msp` now takes **no flip on r** (verified: CW spin
integrates −359°, policy counter-commands left). Commanded-yaw sign through the FC remains
unverified — `fly` keeps `--yaw center`. (2) **MSP_RAW_IMU serves gyro ZEROS until Betaflight's
boot gyro calibration completes** — handling the drone at battery plug-in defers calibration
indefinitely and the policy would see r≡0; ops rule: **leave the drone still ~5 s after plug-in**.
Link re-measured through the bridge at the flying spot: median 19.9 ms RTT, p99 35–54 ms, rare
~520 ms spikes (vs 2.41 ms median on 2026-07-05 — location/RSSI-dependent; still inside the
freshness window, and consistent with the modeled obs-age p50 24 ms).

### Stage 0.5 — `hover_blind` IMU-only first flight (no flow deck)

`hover_blind_air65` trained (40M steps, 2026-07-05): attitude stabilization is excellent
(**1.14° mean tilt, no-DR**), but the trained checkpoint exposed a transferable pitfall —
**deterministic-eval thrust trim is ~12% below hover** (act[0] −0.562 vs the analytic hover
−0.500), so a pure-hold spawn sinks at ~0.35 m/s and floor-exits in median 4 s. Cause
(arithmetically confirmed): **clipped-Gaussian exploration bias** — PPO optimizes the *sampled*
policy, and with final thrust σ=0.478 the clamp at −1 raises the effective sampled mean to
−0.515 ≈ hover; deterministic deployment strips the noise and reveals the low mean. The parent
`hover` masks the same bias via velocity feedback; any *open-loop* channel level learned through
clamped Gaussian exploration will be biased at deterministic deployment.

**Consequence for deployment (pilot.py): a thrust-trim calibration step is MANDATORY, not
optional.** A single scalar trim (+0.0616 on act[0], zeroing v_z at nominal) takes pure-hold
30 s survival from **0% → 100% (no-DR)**. Under full DR no constant trim survives (91% crash
within 30 s) — that is open-loop physics (±5% thrust × ±7% mass), and it is exactly why the
bench-measured hover throttle (~1410 µs @ 3.6–3.7 V) must anchor the real trim: on the bench,
trim until the commanded hover matches true hover, then fly the policy around that anchor.

**Fix shipped (2026-07-05, commit `5c735cd`): all deterministic paths (eval, DeployPolicy
export, Studio Live) now output the closed-form effective mean E[clip(N(μ,σ))]**
(`training/ppo.py::clipped_gaussian_mean`, erf/exp only — TorchScript/ONNX-clean, σ baked into
the export as a buffer). On the 40M checkpoint this alone took pure-hold 30 s survival 0→57%
with no retraining. The **3.2B-step run** (`hover_blind_air65_long`: episode_len 1500 so trim
error integrates to floor exits in-episode, 8192 envs, ~50 min on the 5090) then closed the
rest: exploration σ anneals 0.478→0.032 (clip bias gone at the source), steady-state v_z
+0.01 m/s, **pure-hold 30 s survival 91% no-DR**, median DR-on exit 3.2→8.7 s. The exported
`policy.pt`/`policy.onnx` are now deployment-correct as-is; bench trim calibration remains the
answer to *real* thrust uncertainty (battery sag, prop wear), not to a policy bias.
- Analog VRX → USB capture → gate detector → body-frame target vector; measure detector noise → fold into `DetectorNoise`.
- Flow deck → host-side flow+ToF→velocity estimator; measure error → new flow-velocity DR seam.
- Measure full end-to-end latency → widen `action_latency` DR.

**Measured sim2real gaps from the 2026-07-06 real-flight campaign** (runs/pilot/flight_*.csv;
full 15 s flights, liftoff-seek + RPM governor working). These calibrate the `hover_blind_v2`
sweep configs (`configs/hover_blind_air65_v2*.yaml`):

| gap | measured | sim was | fix |
|---|---|---|---|
| gyro rate-obs noise (calm hover) | **±145 °/s (~2.5 rad/s) sd** from frame vibration | `obs_noise_std 0.01` — a **250× gap** on the policy's primary input (→ constant overreaction, ±10–17° wobble) | per-channel `obs_noise_std_channels` at the measured floor + `obs_stack 3` as the averaging path |
| obs age over the WiFi bridge | p50 24 / p99 112 / max 209 ms | `action_latency_steps 3` (0–60 ms) | `action_latency_steps 5` |
| vz estimate DC bias (in-air) | −0.6..−1.6 m/s in every hover window, even after full-projection + powered 1 g recal | not modeled | `obs_bias_channels` ±1.5 m/s on the new vz_est channel; policy learns what to trust |
| residual level bias after floor-cal | ±2° | not modeled | `obs_bias_channels` ±0.035 rad on roll/pitch |
| same-day hover-anchor spread | ±15% (liftoff-seek re-anchors most of it) | `thrust_scale_frac 0.05` | `thrust_scale_frac 0.12` |
| attitude gains under real noise | steady −3..−10° pitch equilibrium ("drifts backwards"): `upright_sigma 0.5` commands corrections too small to measure over the noise | shallow reward well | `upright_sigma 0.25`, `smoothness_penalty 0.002` |

Altitude remains the structural gap: the external acc-PI damper hit its ceiling (it and the RPM
governor fight over the biased vz estimate), so `hover_blind_v2` feeds the pilot's vz estimate
to the policy as obs channel 6 and the pilot disables the external damper P/I for such policies
(the RPM governor stays — vz is high-passed and cannot see DC thrust error).

> **RESULT (2026-07-06, RED — Flywheel `muddy-hill-9397`).** Training against these gaps
> **backfired**. All three `hover_blind_air65_v2` arms (3.2B steps each) **sink to the floor** —
> no-DR pure-hold 30 s survival **0.0%** vs the `hover_blind_air65_long` baseline's 91.6% — while
> attitude actually *improved* (no-DR tilt 0.69–1.96°). The `_noiseonly` control (baseline reward,
> no vz) still sinks, pinning the cause on the **honest 2.5 rad/s gyro-noise DR itself**: it drowns
> the fine open-loop thrust trim so PPO cannot converge the deterministic hover throttle. The vz
> channel did not close the altitude loop — its input carries the measured ±1.5 m/s DC bias, so the
> leaky acc-integrated estimate is unusable (it *aggravates* the sink). **Conclusion: noise-hardening
> DR is the wrong lever for open-loop IMU-only vertical hover; the fix is the flow deck (real,
> low-bias closed-loop velocity — the Stage-1 `vel_body` pipeline below), not more DR.** The
> `hover_blind_air65_long` checkpoint stays the first-flight policy of record. Metric:
> `scripts/survival_probe.py`.

> **ATTRIBUTION CORRECTED (2026-07-06, Flywheel `quiet-bonus-7296` → `muddy-brook-9314`).** The
> verdict above was **confounded**: `_noiseonly` changed five factors at once vs the baseline
> (noise amplitude, per-episode ±2° attitude bias, thrust 0.05→0.12, latency 3→5, obs_stack 1→3).
> The one-factor follow-up **R1** (`hover_blind_air65_r1.yaml`: honest *white* noise kept, trim
> poisons removed — thrust back to 0.05, attitude bias zeroed, longer curriculum) **still sinks to
> 0.0%** clean survival — so the trim-poison DR is exonerated and the honest noise itself (as
> modeled, i.i.d. **white** at the measured amplitude) is the isolated culprit. Two further
> corrections: (1) DR-on survival with `thrust_scale > 0` is physically unwinnable open-loop, so
> the honest robustness metric is now **split**: M1 = clean-trim no-DR survival (bar ≥ 91.6%),
> M2 = calibrated-trim honest-noise survival (`_m2_honest*` eval configs, bar ≥ 80%) — under M2
> the un-hardened baseline scores **0.1%** (it has zero honest-noise robustness even with perfect
> trim) and the white-noise-trained arms only 3–4%. (2) The deployed gyro is Betaflight-LPF/notch-
> filtered (`pilot.py` `gyroADCf`), so its real noise is **time-correlated** — the sim's white
> injection matches the marginal but not the spectrum. The spectrum hypothesis is under test via
> the AR(1) colored-noise seam (`obs_noise_ar_channels`, marginal-preserving, ρ modeled 0.9/0.8 —
> unvalidated until measured from calm-hover logs): arms R3 (= R1 + colored, one factor) and R2
> (= `_noiseonly` + colored). "Needs the flow deck" remains the strategic read but is **not yet
> forced by the evidence** for the stock-hardware (IMU-only) line.

> **LADDER CLOSED (2026-07-06, RED — Flywheel `muddy-brook-9314` → `spring-violet-3051` →
> `rough-art-1658`).** All three attribution arms failed the bars: **R1** (white noise, trim
> poisons removed) M1 0.0%; **R3** (AR(1)-colored, ρ 0.9/0.8 modeled) M1 0.0% but sink 1.75×
> slower and best-ever no-DR attitude 0.71°; **R4** (+privileged −|vz| / thrust-constancy reward)
> M1 0.0% with median hold stretched to 12.84 s but DR-on tilt collapsed to 40°. Monotone ladder:
> median time-to-floor 2.96 → 5.18 → 12.84 s — each lever attacks its mechanism, none reaches the
> 30 s horizon, and the deploy-relevant M2 got *worse* down the ladder (4.0 → 3.2 → 0.9%).
> **Final attribution: the honest gyro-noise AMPLITUDE itself (2.5 rad/s ≈ 143°/s SD) is what
> sinks blind hover** — not the trim DR (R1), not the white-vs-colored spectrum at modeled ρ (R3),
> not the reward (R4). The v2 conclusion (IMU-only open-loop altitude cannot survive the real
> sensor floor; flow-deck velocity is the path) now **stands with clean attribution**.
> `hover_blind_air65_long` remains the flagship/first-flight checkpoint: 91.6% clean survival,
> 0.1% under honest noise with calibrated trim — fly it in calm air, expect no noise robustness.
> Open honesty items: ρ unvalidated (measure lag-1 autocorr from calm-hover `flight_*.csv`),
> H2 weights unswept.

> **CAMPAIGN REOPENED (2026-07-06, stock-hardware constraint — Flywheel `delicate-credit-2979`).**
> User directive: find a path with **no extra hardware** beyond the stock Air65 II + ESP32 bridge.
> Reframing (`shiny-firefly-6661`): the 2.5 rad/s figure is **aliased frame vibration** at 50 Hz
> MSP sampling, not intrinsic sensor error — the amplitude at the *policy input* is software-
> reducible (bridge MSP oversampling ≈ sd/√N, matched host-side filtering, policy memory). Three
> corrections landed with the first dose-response arm:
> 1. **M2-honest was partly unwinnable** (`odd-hat-1222`): impulse kicks + wind cost the blind
>    baseline ~30 pts *independent of noise* (44.8% vs 15.0% at 0.1× amplitude) — unobservable
>    open-loop kinematics, same fairness class as thrust_scale. Fair metric = **M2-sensor**
>    (`m2sensor_*` configs: calibrated trim, no impulses/wind, honest noise+bias+latency).
> 2. **Zero-noise M1 is unphysical** for a vibration-driven gyro and reads 0% on any noise-trained
>    arm via the Jensen trim shift; the deploy-faithful clean check is **M1-live** (clean world,
>    live sensors — `m1live_d50_s*` configs).
> 3. **The real enemy is the amplitude-LOCKED trim** (`polished-moon-9652`, d50 arm RED): a policy
>    trained at fixed 0.5× amplitude survives 81.4%/43.0%/0.3% at 0.8×/1.0×/1.2× of its trained
>    sd — the learned thrust trim is a steep function of input-noise amplitude, so every
>    fixed-amplitude arm (the whole R-ladder included) was deployment-brittle by construction.
>    Dose-response itself confirmed: M2-sensor@own-amplitude 3.8% (R1) → 22.0% (d50).
> Fix under test: **per-episode noise-amplitude DR** (`obs_noise_amp_range`, commit `1fd3c1e`) —
> d50var trains U[0.5,2.0]× (band 0.625–2.5 rad/s, upper edge = the raw measured floor), so the
> deploy story stops depending on the unvalidated oversampling assumptions.

> **CAMPAIGN CLOSED (2026-07-07 — Flywheel `delicate-credit-2979`, stop_reason no_viable_branch;
> 5 training runs).** Verdict in two halves:
> 1. **The gyro-noise wall is SOLVED in software.** `hover_blind_air65_d50var_s8`
>    (amplitude-DR + obs_stack 8, node `broken-wildflower-8398`, now the **★ studio-baseline**)
>    survives M1-live **89–100% across 0.5–1.2×** the measured amplitude and **61.1% at the RAW
>    2.5 rad/s vibration floor** — the exact condition where the old flagship scores 0.05% and
>    where the v2/R-ladder verdict said "IMU-only cannot survive, needs the flow deck." That
>    strategic conclusion is now **overturned for the noise axis**: no flow deck, no bridge
>    oversampling assumption required. d50var mechanism chain (one factor per arm):
>    amplitude-locked trim (Jensen) → amplitude-DR removes the cliff → capacity lifts the level.
> 2. **The residual gap is a single isolated factor: action latency > ~40 ms during active
>    noise-correction.** Knockout: latency-off takes M2-sensor 29.8→98.2% (bias/rate-gain: nil);
>    per-latency survival ≈ 98/71/10/8/~0% at 0/1/2/3/4+ steps. Three levers failed honestly:
>    action-history echo (`red-fire-4210`, RED — train/eval echo mismatch, fix identified but
>    unbudgeted), measured-jitter distribution-matching (`bold-shadow-8014`, RED — +5 pts on its
>    own distribution, loses noise robustness), honest re-metric alone (s8 under the measured
>    link: 29.6% ≈ the constant hedge — the fragility is physical).
> **First-flight read:** fly `d50var_s8` in calm air — at the bridge's measured p50 (24 ms) it
> sits in its survivable zone; the p99 latency tail (112 ms) is the danger, and shrinking it is
> **bridge work, not policy work** (100 Hz control rate, ESP-side command hold, MSP oversampling —
> which also moves the noise operating point down the amplitude curve into the 90–100% zone).
> Bench checklist before trust: link age histogram (jitter weights are percentile-approximated),
> calm-hover gyro amplitude + lag-1 autocorr at 50 Hz (ρ still unvalidated). New seams on main:
> `obs_noise_amp_range`, `action_latency_dist`, `append_prev_action` (+20 unit tests, suite 183).

> **FIRST GOOD FLIGHT + POLICY EXONERATED (2026-07-07 — `runs/pilot/d50var_s8_f1.csv`).** The
> studio-baseline `d50var_s8` flew its first real flight: **~9 s of near-perfect hover** (stable
> window median tilt **1.28°**, p90 1.67°; policy `a_thr` pinned at −0.50 = textbook hover) then a
> ceiling contact and tumble at ~10 s. Deep-dive of the one surviving log (the multi-battery flights
> were **clobbered** by a `pilot.py` `"w"`-mode overwrite — now fixed to a unique path) gives a clean
> root cause: **the policy is exonerated; the crash was a deploy-harness bug.** The pilot's
> accel-integrated `vz_est` drifted and **railed at its −2.0 m/s clamp by t=8.24 s while the drone
> sat at ~1° tilt** (pure estimator drift). Because this 5-dim policy doesn't consume `vz`, the
> pilot's own altitude damper responded to the phantom sink by piling on thrust — `us_thr` climbed
> **+203 µs while `a_thr` never moved** (IQR 0.015) → climb → ceiling → tumble. The offline
> `scripts/sim_vs_real.py` re-run confirms faithfulness: predicted-vs-logged action **MAE ~2.7e-5**
> (worst 2.2e-4, at the log's 1e-4 rounding floor). **Verdict: fly it again in a taller space; the
> hover itself is solved.**
>
> - **Measurement infra shipped (this block):** `src/neural_whoop/analysis/flight_log.py` (pure
>   load + `flight_metrics`), scalar renderers `viz/render.py::plot_hover_telemetry`/`plot_link_histogram`,
>   `viz/replay.py::flight_to_replay` (Studio-playable real flights; `pos` is a vertical-only stub),
>   and the `scripts/flight_report.py` / `scripts/sim_vs_real.py` CLIs (+ `tests/test_flight_log.py`).
>   Every future flight now gets a rigorous, Flywheel-native pack — no more lost data.
> - **Open honesty item CLOSED — props-on gyro amplitude + ρ** (measured over the 5.18 s stable-hover
>   window, filtered obs-level i.e. what the policy sees): **sd(p)=0.84, sd(q)=0.70, sd(r)=0.03 rad/s**
>   (48/40/1.7 °/s), **lag-1 ρ ≈ 0.70/0.70/0.64**. Two reads: (1) the filtered in-hover amplitude at
>   the policy input (0.7–0.84 rad/s) is **~3× below the raw 2.5 rad/s vibration floor** the amplitude
>   DR band was built around — the loaded, level-hover operating point is milder than the worst case;
>   (2) ρ≈0.7 empirically **corroborates the colored-noise seam** (`obs_noise_ar_channels`, modeled
>   ρ 0.9/0.8) — the noise IS time-correlated, so the marginal-preserving AR(1) model is the right
>   shape (measured ρ is a touch lower than modeled). This is one level hover; sweep more windows/flights.
> - **RPM-anchor `vz` fix — IMPLEMENTED (2026-07-07, awaiting bench flight; Flywheel child of
>   `royal-bar-2003`).** The blind-policy altitude damper in `scripts/pilot.py` no longer rides the
>   accel-integrated `vz_est`; it rides a **driftless RPM-anchored climb rate**
>   (`rpm_climb_rate` = `((rpm/rpm_hover)²−1)·g·VZ_AERO_TAU`) through a pure-**proportional** trim
>   (`rpm_damper_trim`, clamped ±`VZ_TRIM_CAP`). No integrator ⇒ it cannot wind to the −2.0 rail, and
>   at hover RPM the trim is **exactly 0** (statelessly, every frame) — so a level hover can't pile on
>   phantom thrust. Reconciled with the existing RPM governor (`pilot.py` L~820): both now share the
>   one `rpm_hover` anchor and the `(rpm/rpm_hover)²` measurement — the damper is the fast proportional
>   path, the governor the slow command-tracking integral, and the governor's integral **subsumes** the
>   retired accel `i_trim` (`i_trim` / `VZ_ITRIM_*` / `VZ_TRIM_TOTAL` deleted). The accel `vz` stays
>   only for vz-consuming (`hover_blind_v2`) policies and the takeoff-seek breakaway detector. Covered
>   by `tests/test_pilot_vz_damper.py` (14 tests); pilot `selftest` parity unchanged (4.6e-08).
>   **Confirm from the next flight's `flight_report` pack:** `vertical.vz_rail_frames` ≈ **0** over the
>   airborne window (was 48; the logged `vz_est` is now the bounded RPM climb rate),
>   `vertical.thrust_divergence.detected` = **false** with `us_thr_rise` ≲ 40 µs across the stable
>   hover (was +203 µs while `a_thr` never moved), and the hover holds altitude instead of climbing to
>   the ceiling — a completed calm-air flight rather than a ~10 s ceiling contact.
> - **RPM-anchor `vz` fix — VALIDATED IN FLIGHT (2026-07-07, GREEN — Flywheel `aged-wildflower-8839`,
>   child of the impl node `cool-sea-6202`).** 9-flight session (`runs/pilot/flight_17834265xx.csv`),
>   8 airborne. **The ceiling bug is dead.** On the two cleanest long flights (`711`/`678`): `vz_est`
>   is now **driftless** (711 mean **0.00 m/s** over 18 s — in f1 it drifted to −2.0 and *parked*),
>   `vz_rail_frames` **7/13** (was 48), `thrust_divergence` **false** with `us_thr_rise` **−163/−150 µs**
>   (throttle *fell* — was +203 µs into the ceiling), and all three long flights (`678`/`711`/`783`)
>   **completed the full ~18–21 s window and landed under control** (airborne 17.8–18.3 s vs f1's 12.6 s).
>   Honest residual: hover is **wobblier** than f1's pristine window (stable-window median tilt ~1.9–2.0°
>   with ±20–40° transients; several short flights departed early) — traced to the **latency tail**
>   (obs_age p99 73–122 ms, spikes 240 ms), i.e. the campaign's already-isolated action-latency gap
>   (`delicate-credit-2979`), **not** the vz fix. One caveat: `783` flagged divergence (+297 µs) — a
>   *gentle* rise over 18 s at 1.72° reads as battery-sag comp, so the detector needs a sag-normalized
>   threshold for long flights (follow-on). **Verdict: blind-hover altitude is solved in software; the
>   next lever is the p99 latency tail (bridge work), not the policy.**
> - **Deferred — pilot obs-oversampling for the latency tail:** this flight's p99 obs_age is **122 ms**
>   (32% past the 40 ms cliff) — but the bridge RTT p99 is ~24 ms, so the tail is the pilot's 50 Hz
>   single-poll-per-tick coupling, **not** the bridge. Decouple obs polling from the command tick
>   (`scripts/pilot.py` + `bench/msp.py`) — cheap, and it partly overturns the campaign's "fix it in
>   firmware" handoff.

### Horizontal drift → the sensing decision (2026-07-07)

The vz fix closed the vertical loop, but the blind `hover_blind` policy still **drifts horizontally**:
its obs is `[roll, pitch, p, q, r]` only — no position/velocity — so it holds *attitude*, not
*station*. There is **no IMU-only fix** (accelerometer double-integration drifts like the vz ghost we
just deleted). A deep-research pass (Flywheel `bitter-sun-1558` → decision `still-flower-6355`; 15 primary
sources, 73 adversarially-verified claims) settled the path under the user's hard constraints
(nothing off the drone for *sensing*; offboard laptop *compute* OK; cheap/accessible; close to stock):

- **Learned gate/landmark detection + a dynamics-model/IMU beats classical VIO.** MonoRace (TU Delft
  2026, arXiv 2601.15222) beat three FPV world champions with a single **monocular cam + IMU** +
  learned gate segmentation + drone model + EKF (*not* VIO); the 72 g "Trashcan" (arXiv 1905.10110)
  did whoop-mass onboard monocular racing the same way. Classical monocular VIO is the fragile path
  (scale unobservable; SOTA VIO *fails* at racing speed) — but our **offboard laptop** runs VO at the
  300-fps regime, so compute is a non-issue and link latency is the only real cost.
- **Sensor decision — buy ONE module: a XIAO ESP32-S3 Sense (~$15, ~4 g, OV2640), mounted DOWNWARD,
  + a ~$4 VL53L1x ToF on its I²C.** Rationale: the camera is the master key (unlocks horizontal hover
  *and* racing *and* the end-to-end vision policy); the Sense **replaces the plain ESP32 bridge** (one
  module = camera + MSP bridge, not an addition); it's a *separate* camera we can aim **down** for
  clean flow (the easy case, unlike the fixed-forward analog FPV cam); digital frames beat the noisy
  analog feed and cost *less* than an analog receiver. The ToF adds metric height + resolves monocular
  scale → a complete DIY position deck for ~$19.
- **Ruled out:** the analog FPV receiver (inferior forward-facing sensor, ground gear, ~$30); a
  digital-FPV *system* (DJI/Walksnail/HDZero — wrong tool: heavy, $70+, needs its own receiver); UWB
  (swarm-only, deferred, needs one per drone). Full cited analysis in `bitter-sun-1558`.
- **Open risk (the real cost of this route):** streaming video off the ESP32-S3 over WiFi (QVGA
  ~10–25 fps, jittery) *and* keeping the MSP bridge alive on the same chip is unproven firmware work.
- **No-hardware progress in parallel:** open-loop **acro** (flips/rolls/power-loops) needs only the
  IMU — buildable now via teacher-student privileged learning trained in sim (Learning High-Speed
  Flight, Sci Robotics 2021). This is the next build while the Sense ships.

### Unified bench dashboard (tooling, 2026-07-08)

The manual per-flight grind (`export $NW_BRIDGE`, `pilot.py selftest/check`, `pilot.py fly --takeoff
--ack-props-on`, watch a console, re-invoke) is now **one always-on browser page** — the Studio's
**Bench** tab (`docs/STUDIO.md`). The `pilot.py fly` state machine was **extracted verbatim** into a
steppable, pure-stdlib engine (`neural_whoop.pilot.FlightController` + `config`/`policy`/`telemetry`;
`pilot.py` is now a thin CLI shim re-exporting the surface), wrapped in an always-on background
`FlightManager` (`studio/flight.py`) served over `/ws/flight`. Open the page → the bench is connected
→ click **Start** to run the real 3·2·1 → hover → land, watch live telemetry/metrics, optionally
watch a parallel CPU-torch sim of the same policy, and get an auto flight-report on landing.

**The safety interlock is preserved end-to-end and is the design's spine:** the software **Start** only
sets the flight clock, and is **enabled only when telemetry shows ARMED + MSP-OVERRIDE engaged** on the
Pocket. The radio still owns enable + instant kill (drop override / disarm → abort via the ~300 ms MSP
freshness handback). Software never writes arm/aux; stopping the RC stream is the only stop. The real
path imports **zero torch/numpy** and is not gated by the GPU sim's `ROLLOUT_LOCK`. A self-driving
**fake bridge** (`--bridge fake` / `NW_FLIGHT_FAKE=1`) runs the whole dashboard with no hardware, and
backs the headless tests (`tests/test_flight_controller.py`, `tests/test_flight_ws.py`).

### Blind acro flip — take-off → flip → land (harness, 2026-07-12)

The first *agility* deploy path, flown **blind** (IMU-only — no altitude/position/camera). We chose
the **system-level** split: the learned policy owns only the *flip*; the pilot's existing
`3·2·1 → RISE → HOVER → LAND` state machine owns take-off and landing. So "take off, flip, land" =
pilot(open-loop) + policy(learned flip), for both axes (roll `acro_flip`, pitch `acro_flip_pitch`,
each trained GREEN — flip_success_rate 0.845 / 0.840, crash 0.000).

- **Deploy obs (`pilot.obs_from_msp_acro`, obs-7):** `[gravity_body(3), p, q, r, rotation_remaining]`.
  `gravity_body` (`-R[2,:]`) is a pure-stdlib port of the sim's euler→quat→matrix, **byte-parity
  with `tasks/acro_flip.py` (< 1e-6, `test_pilot_acro_obs.py`)** — the make-or-break gate, since a
  mismatch feeds the policy an obs it never trained on. It is yaw-invariant, so deploy passes yaw=0.
- **FLIP window (`pilot/controller.py`):** a bounded maneuver inserted at HOVER. `request_flip()`
  (Bench **Flip** button / `fly --flip-at` / auto `flip_at_s`) is gated to HOVER + fresh link +
  near-level; pressed while still WAITING it doubles as the software Start (same ARMED+override
  gate), arming a pending flip that auto-fires `ACRO_START_SETTLE_S` into free hover — one button
  for take-off → flip → keep hovering.
  A maneuver clock integrates the axis gyro toward Φ=2π·n (`rotation_remaining` 1→0);
  the acro policy drives the rates; FLIP exits → HOVER on rotation-complete + re-level or the hard
  `acro_flip_max_s` backstop, then the hover policy re-stabilizes before the normal LAND.
- **Safety-critical:** the crash detector (a real flip legitimately passes |roll| > 110°), the RPM
  governor, and the climb damper are **suspended only inside the window** and re-arm the instant it
  closes — the bounded window + re-level exit guarantee a *failed* flip that tumbles still cuts.
- **Verified:** sim training + fake-bridge system integration
  (`NW_FLIGHT_FAKE=1 pilot.py fly --takeoff --acro-weights … --flip-at 3`) walks
  WAITING→…→HOVER→**FLIP**→HOVER→LAND→RELEASED with no crash-abort through the inversion. The
  **real-drone flip is NOT validated here (hardware-gated).** Blind-flip altitude is open-loop
  through the inversion (vz freezes > 25° tilt); the flip is sub-second so drift is bounded, but a
  real flight must keep generous ceiling headroom.

### Measured height — VL53L1X on the bridge (hardware, 2026-07-13)

The CJMCU-531 (VL53L1X ToF) arrived ahead of the PMW3901 and is integrated as the bridge's
**downward height sensor** — the first *measured* (non-IMU-integrated) state channel, and the
direct answer to the vz_est-drift smoking gun above:

- **Bridge (`firmware/xiao_bridge`):** sensor on the XIAO's stock I²C (D4/SDA, D5/SCL — free, the
  UART lives on D9/D10), short-distance mode @ ~40 Hz. The bridge answers MSP cmd **192**
  (`MSP_BRIDGE_TOF`, our bridge-local id) itself and never forwards it — transparency preserved for
  everything else, no FC config touched, and the bridge still boots/proxies with no sensor wired.
  Wiring + `bench.py --udp <ip> tof` bring-up in `firmware/xiao_bridge/README.md`.
- **Pilot:** `Telemetry.poll(want_tof=True)` every tick; `tof_m` is CSV column 25 (validity-gated:
  status 0 + age < 200 ms; pre-ToF 24-col logs still load).
- **Flight report:** `flight_metrics()["height"]` (hover mean/sd, max, airborne coverage) and the
  replay's `pos` z becomes the **measured** height (`meta.pos_z_measured=true`; the ∫vz_est
  vertical-only stub remains the fallback). The ceiling-crash class of flight above would now show
  its true altitude trace.
- **Obs channel (2026-07-13, `hover_tof`):** the height-aware hover retrain is implemented — task
  `hover_tof` (obs-6 `[roll,pitch,p,q,r,height_err]` × stack 8; `configs/hover_tof_air65.yaml` =
  the flight-proven d50var_s8 + the channel, setpoint band lowered into the sensor's 0.5–1.1 m
  valid band). Sensor modeled deploy-exactly in-task (~40 Hz ZOH refresh, 1.3 m slant-saturation
  hold, 45° tilt hold); ranging noise sd 0.02 m / bias ±0.03 m ride the per-channel DR —
  **datasheet placeholders until the first ToF-equipped flight calibrates them**. Deploy: the pilot
  feeds `--target-height − tof·cosr·cosp` (flat-floor tilt correction), last-valid-held; the family
  is keyed off the export meta's `task` (a 6-dim file without it stays the vz family); setup
  refuses to fly without a live ToF and >1 s in-flight silence aborts (`tof_lost`); the external
  climb damper turns OFF (the policy owns altitude; RPM governor stays). The exact fed channel is
  logged as CSV col 26 `h_err`, so `sim_vs_real.py` replays it byte-exactly.
- **Next uses:** height ground-truth for vz_est error characterization → flow×height velocity
  fusion when the PMW3901 lands (ROADMAP #9).

### Stage 2 — Closed-loop `hover` / position-hold
Simplest closed-loop flight; validates the full latency budget end-to-end. Reuses the `hover` task + Studio Live disturbance seam (`add_velocity`/`add_body_rate`).

### Stage 3 — `gate_race` on a real marked track
Real gates with visual markers; lap-time metric vs sim.

### Later (deferred)
Onboard quantized policy in firmware (G473); honest camera-only perception without the flow deck; swarm.

## Control/compute-path branch map (2026-07-03, hardware purchased)

Where the policy runs × how commands reach the FC. Researched (web, sources in the Flywheel node)
now that the Air65 II is bought. Verified I/O facts first:

- **FC I/O (Matrix 1S 5IN1 II, STM32G473CEU6):** 4 UARTs — UART2=VTX, UART3=onboard ELRS RX
  (removable via a resistor), **UART1 + UART4 free** for a companion. Ships with a BF 2026.6.0
  custom build.
- **Betaflight external-control seams:** (a) **MSP override** (`msp_override_channels_mask` +
  MSPRCOVERRIDE mode) — real and current; `msp_override_failsafe` (BF 4.5+, PR #13380) fixes the
  RC-loss failsafe trap; per-channel **300 ms freshness window**; serviced at ~**100 Hz** default
  (`serial_update_rate_hz` raises it). (b) Companion **emulating a CRSF receiver** into the RX
  UART — electrically plausible (416 kbaud, 250 Hz+), **no confirmed working writeup** (BF
  discussion #14064 failed unanswered); treat as unproven. (c) **MAVLink serial-receiver provider**
  (BF 2025.12+, pairs with ELRS MAVLink mode at 460800) — genuine bidirectional RC+telemetry on one
  link.
- **Offboard ELRS uplink is proven:** host/RPi driving an ELRS TX module's CRSF pin directly
  (RC_CHANNELS_PACKED at ~250 Hz, e.g. RadioMaster Ranger Micro at 460800) binds and flies a BF
  quad; single-digit-ms OTA at 250–500 Hz. `elrs-joystick-control` does gamepad→CRSF→module.
- **Pinned weights (BetaFPV spec tables, 2026-07-04):** Air65 II dry = **17.7 g Racing** / 17.8 g
  Freestyle / 16.6 g Champion; LAVA II 1S = **8.2 g (320 mAh)** / 6.8 g (280 mAh), BT2.0. So base
  AUW ≈ 25.9 g (Racing + 320), and the bridge stack ≈ **29.5–31.5 g** (+ ~2 g flow deck + plain
  XIAO ~3 g — the camera-less XIAO suffices for branch B; the Sense (~5 g w/ camera) is a branch-D
  part). No published bare-board XIAO weight exists (retail "14.68 g" is packaged); ~3 g is
  inferred from same-size boards — the one number still worth a real scale eventually.
- **ESP32 companion (Seeed XIAO ESP32-S3 / Sense):** ~3–5 g class (see pinned weights above),
  8 MB PSRAM/flash, camera on Sense (OV2640/OV3660, detection-class vision ~3–10 fps CNN, maybe
  15–30 fps for cheap blob/marker — unbenchmarked). **ESP-NOW ≈ 5.6 ms median** link latency
  (100–200 Hz plausible), WiFi UDP ~9 ms tuned (jittery untuned), BLE floor 7.5 ms. **BLE-only (no
  BT Classic)**: Xbox Series pads pair via Bluepad32 (fw 5.15+ is BLE); PS4/PS5/Switch pads need BT
  Classic (original ESP32). TinyPolicy-size int8 MLP ≈ 0.1–0.4 ms via esp-nn (extrapolated).
  Prior art: DroneBridge/ESP32 (MSP over ESP-NOW/WiFi, the exact companion pattern), esp-drone,
  esp-fc. Payload cost: +4–6 g → ~29–31 g AUW, TWR ~3.5–4:1 — flyable, ironically back inside the
  old Meteor75-massed DR band.

The branches (all share the Stage-0 bench work; latency band is the DR knob that differs):

| Branch | Path | Command seam / rate | Latency band | Status |
|---|---|---|---|---|
| **A. Offboard ELRS** *(plan of record)* | host policy → ELRS TX module → onboard RX | CRSF 250 Hz | ~40–100 ms end-to-end (camera loop) | First flight path — proven, real failsafe, manual takeover on same link |
| **B. ESP32 bridge** | host policy → ESP-NOW → XIAO on UART1 → MSP/CRSF into FC | MSP ~100 Hz (default) | ~20–50 ms | Solves the flow-deck **downlink** (companion reads flow+ToF, ships telemetry back); gateway to D |
| **C1. Gamepad via host** | Xbox pad → PC → CRSF → ELRS module | 250 Hz | ~10–20 ms | The manual-fallback rig; build immediately with A |
| **C2. Gamepad direct-to-drone** | Xbox pad → BLE → onboard XIAO → FC | BLE ≥7.5 ms interval (~133 Hz) | ~15–30 ms | Fun demo (no radio, no PC); off critical path |
| **D1. Fully onboard** | XIAO runs int8 policy; flow (+Sense camera) obs; UART to FC | MSP/CRSF local | ~5–20 ms (**lowest**) | Post-Stage-2 branch: **onboard `hover` needs no camera** — flow+FC-attitude obs only |
| D2. Policy in BF firmware (G473) | — | — | lowest | Stays deferred (RAM-tight) |

Notes: (1) The uplink/action **split-latency DR seam** already in the env (`uplink_latency_steps` /
`uplink_interval_steps`, `docs/CONTRACT.md`) is exactly how these branches differ in sim — each
branch is a DR config, not new code. (2) Branch B directly resolves the "flow forwarding may need a
tiny companion MCU" open risk below. (3) D1's obs problem decomposes: `hover`/position-hold needs
only flow-velocity + attitude (no perception), so "fully onboard hover" is a realistic near-term
milestone; onboard gate perception is the hard tail.

## Sim-side work startable now (no hardware)
1. Air65 II airframe DR re-center (mass/inertia/arm/TWR) — config + `whoop.py`.
2. Widen `action_latency` DR to a realistic offboard range; consider 100 Hz control.
3. Add the flow-velocity DR seam (dropout, height-coupling, latency) in `randomization.py` — counterpart to `DetectorNoise`.
4. Turn on `DetectorNoise` for a camera-perception racing config.
5. Re-train + re-eval `hover` and `gate_race` under the new DR; confirm in Studio.

## Bill of materials
**Stage 0 (order first):**
- BetaFPV **Air65 II** (Racing, 0702 30kKV), Analog, ELRS 2.4 GHz.
- 1S batteries (BT2.0/A30, ~300 mAh) ×6+ and a 1S charger.
- ELRS radio/TX for binding + manual-pilot backup (e.g. RadioMaster Pocket ELRS) — also the MSP uplink path.
- Spare props / motors / frames (whoops crash).

**Stage 1 (perception + velocity):**
- Analog 5.8 GHz VRX with USB/AV out + USB capture card (host-side video in).
- Optical-flow + ToF module: **Matek 3901-L0X** (UART, MSP V2) or a Bitcraze Flow Deck v2 (PMW3901+VL53L1x, ~1.6 g) for the raw-SPI route. Wire to the free **UART1**.
- Gate markers (AprilTags / LED rings / colored gates) for robust low-res detection.

**Branches B/C2/D1 (companion, optional — order when branch opens):**
- Seeed **XIAO ESP32-S3 Sense** (~3–5 g w/ camera; weigh it) + a plain XIAO ESP32-S3 as the
  host-side ESP-NOW peer. Xbox Series controller (fw ≥5.15, BLE) for C2.

## Idea backlog: apartment-scan environment via Meta Quest 3 (2026-07-04)

User owns a Quest 3 — scan the apartment, train against the real geometry, then fly the *same*
course in the *same* room (collapses the Stage-3 sim↔real course gap to ~zero). Sketch:

1. **Export the scan.** Quest 3 Scene Mesh (depth-sensor room mesh) via a small in-headset app →
   OBJ/GLTF; fallback: walk-around video → photogrammetry/splatting on the 5090.
2. **Mesh → SDF.** Bake a voxel signed-distance field (~5 cm, a torch tensor) — batched
   GPU-friendly collision the way the env already works; keep the GLTF for viz.
3. **Env seam: obstacle field.** New DR-compatible collision seam (termination + distance penalty +
   spawn validity) sampled from the SDF; course YAML authored in apartment coordinates.
4. **Viz.** Apartment mesh as the Studio / nw-viz backdrop (three.js loads GLTF natively) — hero
   MP4s of the policy flying through *your actual living room*, pre-flight.
5. **Real flight** (branch A offboard) on the matching physical course.

Sub-ideas: Quest controller as a **gate-authoring wand** (touch a point in the room → gate pose in
the scan frame — solves course registration); MR ground station (telemetry overlaid on the real
drone); Quest hand-tracking as the real counterpart of the `hand_follow`/`gesture_follow` tasks.
Open problems: mesh-export friction (Scene Mesh needs an app with scene permission), scan accuracy
(~2–3 cm class), and **frame registration** — aligning the drone's world frame to the scan frame is
the real work (the wand idea + a known takeoff point is the likely answer).

## Open risks / unknowns
- **Flow on a whoop:** Betaflight won't fuse it — we own the estimator host-side; mounting a downward sensor unobstructed by battery/frame is fiddly; may need a tiny companion MCU if UART forwarding is messy.
- **MSP override + failsafe:** known Betaflight pain (issues #12790/#13374); must keep a manual-pilot fallback.
- **Analog FPV** is low-res/noisy — detection wants marked gates; capture card adds latency (budget it into DR).
- **Latency** is the dominant offboard risk; measure early, model honestly.
