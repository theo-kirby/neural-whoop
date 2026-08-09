---
node_id: 3d0349b9-ec32-5e01-9de4-db696d00b2c4
slug: lucky-lodge-5696
title: 'Hover deployment: the 1.0 m setpoint is outside the sensor''s trusted band, and Desk-Hover has never been flown'
created_at: '2026-08-09T18:42:33+00:00'
parents:
- modest-raven-7153
summary: The shipped 1.0 m hover policy crashed every real flight that reached its setpoint, by a five-step mechanism measured in flight. Flying lower at 0.7 m still does not settle. Desk-Hover moves the operating point to 0.10 m so the mechanism is structurally absent, scores 3 of 4 pre-registered gates in sim, and has never been flown.
---
Status: broken

## Current

The shipped policy is `hover_tof_air65_w128u15`, chosen by the user at the second
regroup after four one-factor arms mapped a clean-trim-versus-noise-robustness
frontier with no gate-dominant point [rec: white-rice-3299]. Deploying it at its
1.0 m target is **broken**, and the mechanism is measured rather than guessed
(`docs/SIM2REAL.md`, 2026-07-31): the climb crosses the setpoint at 1.2-1.9 m/s and
the brake is about 0.13 s late; `act[0] = -1.0` maps to motors off; the overshoot
exits the VL53L1X's ~1.3 m trusted band; `h_est` is then held indefinitely so `h_err`
pins at about -0.29 m — a dead sensor telling the policy it is far above target — and
it commands motors-off open-loop into the floor at about 2 m/s. Four ESP-NOW flights
peaked 1.36-1.37 m against a 1.0 m target; the one flight of four that stayed inside
the band is the one that did not crash.

Three deploy-side guards followed [rec: black-salad-4817], all defaulted on and all reversible: fly
`--target-height 0.7`, a `--min-thrust-frac 0.25` free-flight throttle floor, and a
`--tof-blind-grace 0.2 / --tof-blind-fade 0.3` fade so a stale ToF error decays to
"at target" rather than being held forever. The blind fade is a deliberate deviation
from the trained observation contract, recorded as such.

At 0.7 m it still does not settle. Three flights gave clean 3.3 s hover windows at
about 2.8 degrees median tilt, but all three oscillated vertically with peaks of
1.20-1.34 m still kissing the ceiling from a 0.7 m setpoint, and flight 3 tumbled
[rec: broken-fire-4858].

**Desk-Hover** (`configs/desk-hover.yaml`, still `task: hover_tof`) answers this by
moving the operating point rather than the sensor suite: at 0.10 m the same measured
0.37 m overshoot reaches 0.47 m, thirteen times inside the ceiling, so steps 3-5 of
the chain *cannot occur* [rec: black-salad-4817]. Arm 1 scores 3 of 4 pre-registered
gates and beats the 1.0 m parent on the same battery, which scores 0 of 4
[rec: dawn-bonus-9868]. **It has never been flown**, and the gate it misses is the
floor-exit gate.

## Negative knowledge

- [scope: penalising horizontal velocity to reduce hover drift | confidence: high | evidence: soft-breeze-8148] Desk-Hover arm 2 (`vxy_penalty` 0 to 0.5) is NO-GO, and the mechanism is why a bigger weight will not help either. The corrective move a hovering policy makes against perceived drift IS horizontal speed, so with a clean attitude estimate the penalty is nearly free and collects the drift reduction, and once the gyro channels are noisy it suppresses exactly the corrections needed — drift gets worse under every noise twin. Pressing toward stillness also biases the hover lower, and at desk scale the thing below is 8 cm of floor: floor exits went 98 to 311.
- [scope: open-loop IMU-only vertical hover | confidence: high | evidence: muddy-hill-9397, muddy-brook-9314, spring-violet-3051, rough-art-1658] A four-arm attribution ladder established that the honest 2.5 rad/s gyro-noise amplitude itself makes the open-loop thrust trim unlearnable — not the trim-poison DR (R1), not the white-versus-colored spectrum at modelled rho (R3), not the reward (R4). Median time-to-floor improved monotonically 2.96 to 5.18 to 12.84 s and nothing reached the 30 s horizon.
- [scope: the conclusion 'IMU-only cannot survive, it needs the flow deck' | confidence: high | evidence: broken-wildflower-8398, delicate-credit-2979] That strategic conclusion was itself overturned for the noise axis. Per-episode noise-amplitude DR plus obs_stack 8 survives 89-100% across the deploy band and 61% at the raw measured floor where the old flagship scored 0.05%. The real enemy was the amplitude-LOCKED trim of fixed-amplitude training, which made every fixed-amplitude arm deployment-brittle by construction. No flow deck and no bridge-oversampling assumption were needed.
- [scope: a near-range tof_min_m validity gate | confidence: high | evidence: black-salad-4817] Considered and rejected as actively dangerous. The sensor reads a stable 23.9 mm mean with 2.4 mm sigma at rest, so there is no near-range invalidity to model; a 0.04 m gate against `bound_z_min 0.010` would create a 3 cm dead band exactly where the drone dies, freezing the height channel to say 'at target' while it descends into the desk. That is the identical confidently-wrong-held-channel shape as the ceiling crash, pointed at the floor.

## Provenance

- white-rice-3299 — the shipped 1.0 m policy and the user decision behind it
- broken-fire-4858 — the first real ToF flights at 0.7 m and what they did not achieve
- noisy-brook-4394 — retraining at the honest 25 Hz sensor rate, 3 of 4 gates
- black-salad-4817 — the Desk-Hover design and the structural argument for the operating point
- dawn-bonus-9868 — Desk-Hover arm 1 trained, 3 of 4 gates
- soft-breeze-8148 — arm 2, NO-GO, and the mechanism
- delicate-credit-2979 — the closed stock-hardware campaign that solved the noise axis
- broken-wildflower-8398 — the amplitude-DR policy that overturned the flow-deck conclusion
