---
node_id: 7690e89b-fc02-5911-a76e-4082290f25a3
slug: billowing-paper-5404
title: 'Idea: blind acro is shippable NOW — train the coded-but-untrained acro_flip on the 5090 + build the pilot acro harness'
created_at: '2026-07-11T17:08:21.033958+00:00'
parents:
- fancy-rice-9295
- shiny-violet-1747
summary: 'acro_flip is fully coded (task + barrel-roll/pitch configs, obs 7-dim [gravity_body,p,q,r,rotation_remaining]) but has NEVER been trained and there is NO pilot flight path for it (check_policy_family refuses anything but hover_blind''s obs 5/6). SOTA says blind is SUFFICIENT for a single attitude maneuver: Deep Drone Acrobatics ablation shows IMU carries the maneuver and vision only fixes inter-maneuver drift, and a Crazyflie-Brushless double backflip fits in 1.8 m. Two-part effort: (1) 5090 — train acro_flip to a Studio verdict; (2) bench — add obs_from_msp_acro + a maneuver trigger + relaxed family check so a flip can actually be flown. The recovery phase (not the rotation) is the binding constraint given ~2:1 TWR; add ToF later for flare height. Idea/setup.'
origin:
  backend: flywheel
  node_id: 7690e89b-fc02-5911-a76e-4082290f25a3
  slug: billowing-paper-5404
  revision: 1
  exported_at: '2026-08-09T18:23:28+00:00'
---
# Idea: blind acro now — train acro_flip + pilot acro harness

## Framing
The agility beachhead already has code but no results and no flight path. Acro is the task that best fits the CURRENT blind obs: it's attitude/rate tracking with a known thrust profile, not station-keeping. SOTA says exteroception is optional for a SINGLE maneuver.

## Two-part work
**A. Train (5090).** Run the existing `acro_flip` / `acro_flip_pitch` configs to convergence; get the first real agility verdict (success rate, recovery tilt, crashes) with a Studio hero replay. Structure the maneuver: entry from the hover operating point → gyro-tracked rotation → recovery to hover within an altitude budget.

**B. Pilot acro harness (bench, here).** Today `pilot.check_policy_family` refuses base_obs_dim ≠ 5/6 and `obs_from_msp` only builds `[roll,pitch,p,q,r]`. Need: `obs_from_msp_acro` (build the 7-dim acro obs incl. gravity_body + rotation_remaining bookkeeping), a maneuver trigger (a button/stick that arms the flip from stable hover), and a relaxed family check. Radio still owns enable+kill.

## SOTA basis
- Deep Drone Acrobatics (Kaufmann/Scaramuzza, RSS 2020): power loop / barrel roll / matty flip zero-shot; ablation — IMU dominates during the high-g maneuver, vision only bleeds inter-maneuver drift. Blind = sufficient per maneuver.
- Crazyflie-Brushless sysID + RL double backflip in 1.8 m (2026); TACO / Reactive Aerobatics (2025) zero-shot extreme aerobatics via curriculum+DR.

## Risk
Budget thrust headroom: ~2:1 TWR makes RECOVERY, not rotation, the binding constraint. Chained maneuvers / precise recovery positioning are where blind fails — keep to single maneuvers until flow/ToF land.

## Lineage
Parents: roadmap hub (Tier-1.3 + Tier-2.7), and the acro_flip GREEN node (the task this trains + gives a flight path).