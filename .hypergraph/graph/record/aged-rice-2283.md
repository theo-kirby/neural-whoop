---
node_id: 2c503af5-ec81-5c32-bdbc-7cc54842bcaf
slug: aged-rice-2283
title: 'Branch: auto-stability — disturbance rejection / hover-hold as a first-class objective'
created_at: '2026-06-27T16:18:39.769716+00:00'
parents:
- winter-sun-1382
- floral-sunset-3918
summary: 'Placeholder branch (not started) opening auto-stability as its own workstream: make disturbance rejection / hover-hold a first-class task objective rather than a side effect of the DR seam — hold a position/attitude setpoint and recover quickly from arbitrary external disturbances (shoves, gusts, a dropped ball, a teammate''s wake). It would add new DroneTask(s) (hover_hold / recover) with recovery-time + steady-state-hold-error metrics and a disturbance-injection training regime (an external-wrench/impulse channel), distinct from the racing reward. A foundation robustness capability our racers were never explicitly trained for; seeded by the Studio interactive-perturbation idea, no task implemented yet.'
origin:
  backend: flywheel
  node_id: 2c503af5-ec81-5c32-bdbc-7cc54842bcaf
  slug: aged-rice-2283
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: f81fb85f-88c6-557c-80c7-93563197378e
  slug: icy-credit-7290
  revision: 0
  pushed_at: '2026-08-09T21:27:05+00:00'
  content_sha256: 906307dc702f7bd009a4ca895896dfb60405b502dae5bfde15395285f29c2211
---
## Status: PLACEHOLDER BRANCH (not started)

## The idea
Every policy so far optimizes a *task* (race gates, fly a swarm) and gets robustness only as a side effect of the DR seam. **Auto-stability makes robustness the objective itself**: hold a setpoint (position and/or attitude) and **recover quickly from arbitrary external disturbances** — a shove, a wind gust, a dropped object, a swarm teammate's wake. This is what makes a whoop feel ‘locked in’ and is directly testable by hand (see the interactive-perturbation Studio idea, this node's parent).

## What the branch contains (candidate nodes later)
- **New DroneTask(s)**: `hover_hold` (minimize position/attitude error at a setpoint) and/or `recover` (start from a kicked/tumbling state, return to stable hover). Metric: **recovery time** + **steady-state hold error** + crash rate; reward = setpoint error + control effort.
- **Disturbance-injection training**: extend the env with an **external-wrench / impulse channel** (force kicks, gust bursts, optional contact with a dropped body) sampled during training — the same dynamics primitive the interactive Studio needs, used here as a training disturbance distribution rather than a UI toy.
- **Transfer story**: position hold needs a position estimate (mocap / VIO / flow) — ties into the perception branch; attitude-only stabilization is cheaper (IMU is enough) and a good first target.
- **Eval**: kick the policy with a held-out impulse distribution; measure recovery time + max excursion. Compare an explicitly stability-trained policy vs a racing policy shoved the same way.

## Why it's its own branch
It's a different *objective family* from gate-chasing — a foundation capability (a stable inner behaviour) that other tasks could build on, and the most hands-on-demoable robustness story.

## Lineage
- builds-on `ff881809` (the dynamics + CTBR control baseline this stabilizes).
- builds-on `2ed708fd` (the interactive-perturbation Studio harness — the by-hand way to probe + demo stability, sharing the external-wrench primitive).