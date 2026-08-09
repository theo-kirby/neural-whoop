---
node_id: 776502e7-48c9-5500-ba1e-b0bb1dd47ad9
slug: steep-mountain-4778
title: 'Idea: hover_low — a 0.1 m ultra-still hover task (stillness as the metric, ground effect as the honest sim2real gap, crashes nearly free)'
created_at: '2026-08-08T13:06:33.550376+00:00'
parents:
- broken-fire-4858
summary: 'Next 5090 session (Theo''s direction, 2026-08-08): train a policy that hovers ~0.1 m off the ground and stays as still as possible. Motivations, in order: (1) it attacks exactly what the first real-ToF flights (broken-fire-4858) showed failing — vertical oscillation with vz railing — by making stillness itself the reward rather than a byproduct; (2) it lives in the ToF''s sweet spot: 0.1 m is far from the 1.3 m ceiling (the observed peaks kissed it even from a 0.7 m setpoint) and well above the 23.9±2.4 mm sensor floor (tiny-glitter-0842); (3) a 0.1 m drop is a harmless crash — today''s tumbling crash from height forced a full rewire, and this task makes real-world iteration cheap; (4) it opens a genuinely new sim2real question: ground effect at ~3 prop-diameters is real and DiffAero does not model it, so the sim-vs-real still-hover comparison MEASURES the ground-effect gap. Design notes: hover_tof task family should mostly transfer (obs unchanged, target-height 0.1); refit the h-noise/gyro DR first from flight 2''s calibration numbers (sd p/q/r 0.091/0.108/0.082 rad/s, lag1 ρ 0.60/0.62/0.82); metric = stillness in the stable window (height sd, tilt sd, velocity sd — flight_report already computes these for real flights, so sim and real grade on the same numbers); mind the min_thrust_frac 0.25 floor interaction — at 0.1 m a -0.75 g brake is instant ground contact.'
origin:
  backend: flywheel
  node_id: 776502e7-48c9-5500-ba1e-b0bb1dd47ad9
  slug: steep-mountain-4778
  revision: 1
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: a9e9288c-682c-5255-bff9-d74ff9debc5a
  slug: royal-wildflower-8283
  revision: 0
  pushed_at: '2026-08-09T21:28:18+00:00'
  content_sha256: f9c96dfe5420404a0d61f460a583ae3283b86610245c5c7a5d5a7bb532bd7646
---
## Idea

Train a policy whose whole job is: sit at ~0.1 m and do not move. Proposed by Theo after the first
real-ToF flight session (`broken-fire-4858`), before starting the next training session on the
5090.

## Why this task, now

1. **It is the observed failure, inverted into an objective.** All three real flights oscillated
   vertically (vz railed at the ±2 m/s clamp 7–14% of airborne frames). hover_tof rewards being
   *at* a height; it does not specifically reward being *still*. A task whose metric is stillness
   (height sd / tilt sd / velocity sd in the stable window) optimizes the failing axis directly.
2. **Sensor sweet spot.** 0.1 m is far from the 1.3 m VL53L1X ceiling that today's flights kissed
   even from a 0.7 m setpoint, and comfortably above the measured 23.9 ± 2.4 mm floor
   (`tiny-glitter-0842`). The ToF is at its best exactly where this task lives.
3. **Crashes become nearly free.** Today's crash from height forced a full rewire. A 0.1 m drop is
   a non-event — real-world iteration on this task is cheap, which matters while the airframe and
   link are still being debugged.
4. **A new, honest sim2real gap: ground effect.** At ~0.1 m a 31 mm-prop whoop sits around 3 prop
   diameters — ground effect is real there and DiffAero does not model it. The sim-vs-real
   still-hover comparison therefore *measures* the ground-effect gap; if the policy is
   systematically thrust-rich near the floor in reality, that number is the model error.

## Design sketch (for the 5090 session to refine)

- Start from the hover_tof task family — obs-v4 + tof channel unchanged, target height 0.1 m.
  Likely a config first (`target_height: 0.1` + stillness-weighted reward), a new task only if the
  reward shape demands it.
- **Refit the DR first**: flight 2 of `broken-fire-4858` provides the first in-flight calibration
  numbers — props-on gyro sd p/q/r = 0.091/0.108/0.082 rad/s, lag1 ρ = 0.60/0.62/0.82, plus real
  ToF traces at 71–93% coverage. The placeholder h-noise DR should become these numbers before the
  new task trains against it.
- Metric parity with reality for free: `flight_report.py` already computes stable-window height
  sd / tilt sd for real flights — grade the sim policy on the same statistics so the sim→real
  comparison is number-to-number.
- Watch the `min_thrust_frac 0.25` interaction: at 0.1 m, a −0.75 g braking command is ground
  contact within ~0.16 s. The floor that saves a 0.7 m hover may need rethinking at 0.1 m — or the
  reward should simply make large downward commands unattractive.
- Spawn/curriculum: spawns near the floor mean ground-plane termination logic gets exercised from
  step 0; check the env's crash/ground handling rewards settling rather than terminal-penalty
  avoidance hovering high.

## Lineage

- Parent `broken-fire-4858` — the flight session whose vertical oscillation + crash this task
  answers, and whose flight-2 data calibrates the DR it should train under.