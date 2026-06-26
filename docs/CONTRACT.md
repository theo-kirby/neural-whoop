# The policy ⇄ env contract (obs / act / DR)

The contract is the sim2real seam: the exact interface a real whoop also exposes. It is
simulator-independent (pure batched torch in `src/neural_whoop/contract.py`) and unit-tested without
DiffAero. The env fills these from DiffAero state; on hardware the same functions would run against
onboard estimates.

## obs-v4 (length 11) — body-frame, heading-invariant

| idx | field | meaning |
|----:|-------|---------|
| 0–2 | `gx, gy, gz` | target-relative vector, **body frame** (next gate center, or a movable-target estimate from the perception front-end) |
| 3–5 | `vx, vy, vz` | linear velocity, **body frame** |
| 6–7 | `roll, pitch` | gravity-tilt (yaw dropped — not observable without a magnetometer) |
| 8–10 | `p, q, r` | body angular rates (gyro) |

Heading-invariant by construction: everything is rotated into the body frame and absolute yaw is
dropped, so the policy generalizes over the drone's world heading. Body frame: **+x forward**
(camera axis), **+y left**, **+z up**. `build_observation()` assembles it; `world_to_body(v, R)` is
the single source of the frame convention (`R` = body→world rotation, so world→body is `Rᵀ`).

Tasks may append fields after the 11. `gate_race` appends a **3-vector body-frame lookahead to the
next gate** (racing-line planning) → `obs_dim = 14`.

## act-v2 (length 4) — CTBR, normalized [−1, 1]

| idx | field | maps to |
|----:|-------|---------|
| 0 | `collective_thrust` | `[-1,1] → [0, max_thrust_normed]` (DiffAero normed thrust; **1.0 == weight-cancelling hover**) |
| 1 | `roll_rate`  | `[-1,1] → ±max_body_rate_rp_rps` |
| 2 | `pitch_rate` | `[-1,1] → ±max_body_rate_rp_rps` |
| 3 | `yaw_rate`   | `[-1,1] → ±max_body_rate_yaw_rps` |

CTBR = collective-thrust + body-rates, exactly what Betaflight's acro rate loop takes. This is the
real seam a whoop exposes: the policy commands thrust + body rates and observes IMU-derivable
quantities. `action_to_diffaero()` performs the mapping (defaults in `ActionLimits`:
`max_thrust_normed=4.0` → TWR ≈ 4, `±12 rad/s` roll/pitch, `±6 rad/s` yaw). The deterministic
deploy action is `clip(actor_mean, −1, 1)` — the same network that trains is what exports.

The inner loop (CTBR → motor torque) is DiffAero's `RateController` with a domain-randomized
rate-loop bandwidth (`K_angvel`) — that randomization *is* the unknown-Betaflight-tune gap.

## Domain randomization (the sim2real lever)

Two layers combine; training across them is what makes a tiny policy transferable.

**Airframe DR** — inside DiffAero's `QuadrotorModel`, refreshed per-episode *in place* by
`WhoopDynamics` (preserving the controller's live mass/inertia references):

| knob | default range | models |
|------|---------------|--------|
| mass | 0.028–0.036 kg | build/mass tolerance |
| arm length | 0.028–0.036 m | frame geometry spread |
| torque constant | 0.005–0.008 | motor/prop spread |
| inertia `J_xy / J_z` | ±~10 % | mass distribution |
| drag `D_xy / D_z` | 0.08–0.12 | aero spread |

**Seam DR** — `src/neural_whoop/randomization.py` (`DomainRandomizationConfig`), everything DiffAero
doesn't model:

| knob | default | models |
|------|---------|--------|
| `wind_accel_mps2` | 1.5 | steady wind (per-episode direction + magnitude) |
| `rate_gain_frac` | 0.15 | unknown Betaflight rate-tune (commanded-rate scale) |
| `thrust_scale_frac` | 0.10 | motor-strength / battery-sag spread |
| `obs_noise_std` | 0.01 | noisy onboard estimates |
| `action_latency_steps` | 1 | sense→infer→actuate delay (per-drone ring buffer) |
| `detector_*` | off (baseline) | blob/depth detector error: bearing / range / FOV / dropout (in `perception/`) |

Detector noise is **off for the state-based racing baseline** (first beachhead avoids the camera
path); it turns on for the camera-only follow tasks, applied to the oracle's body-frame target
vector with stale-hold on a miss.

## Versioning

If you change obs/act/DR **semantics** (not just weights/ranges), bump the version (obs-v5 / act-v3)
and document why here and in `CLAUDE.md`. The whole point of this seam is that it stays stable and
explicit across sim and hardware.
