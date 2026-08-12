---
node_id: 1b5427db-55ee-5aac-92bc-9eaa82ecb5ff
slug: lucky-bramble-8001
title: The obs-8 deploy path rehearses FAITHFUL at 0.20 m, after the fake bridge could not fly it and sim_vs_real could not pass it
created_at: '2026-08-12T21:54:17+00:00'
parents:
- restless-oak-1375
summary: ''
---
## What

The obs-8 deploy path rehearsed end to end against the fake bridge at the 0.20 m setpoint, and
**`sim_vs_real` reports FAITHFUL — worst |err| 1.05e-04 over 745 graded rows of 1063**, against the
CSV's own 1e-4 rounding floor. Getting there required fixing two defects that the rehearsal existed
to find and that reading the code would not have found. Commits `994bcf7`, `a121f78`.

Artifacts: `runs/desk-flow/rehearsal_report/` (flight_telemetry.png, link_histogram.png,
flight_summary.json, flight_metrics.csv, replay.json.gz, run.json) from
`runs/pilot/flight_1786570346.csv`; `runs/desk-flow/policy_weights.json` +
`policy_ref_outputs.json`.

## Why

`restless-oak-1375` produced a graded 0.20 m policy. Phase 4's preconditions are hard by design —
`selftest` parity, a full `WAITING -> ... -> RELEASED` fake flight with `h_err`/`vx`/`vy`
byte-exact, `sim_vs_real` FAITHFUL — because the alternative is discovering a channel-semantics bug
on a real airframe. The rehearsal is the only thing standing between the sim result and hardware.

## Method

`export_json.py` -> `pilot.py selftest` -> a 15 s fake-bridge flight -> `sim_vs_real.py` ->
`flight_report.py`.

`selftest` passed first time: parity 5.01e-08 across 12 probes, and — the part that matters for a
new obs family — the **corrective signs on the two new channels** are right. Drifting forward
(vx +0.2) commands `pitch_us` 1466, a nose-up brake; drifting left (vy +0.2) commands `roll_us`
1529, a roll-right brake.

## Result

**Defect 1 — the fake bridge had THREE disagreeing hover points, and a `hover_flow` policy could
not take off at all.** Its accelerometer model implied weight-balance at 1300 us, its height
integrator hard-coded 1450, and `FlightParams.hover_us` is 1410. The pilot learns its hover anchor
from acc-z during the liftoff seek (1337) and then flies against the height the ToF reports — so it
commanded a throttle that, in the height model, was a *descent*. The drone never left 0.030 m,
never reached the PMW3901's 0.08 m working range, and the flight died on `flow_lost` one second
into free flight. Every one of those subsystems is individually plausible, which is why this needed
running rather than reading.

Pinning all three at `hover_us` flew it. The acc gain also had to move 3 -> 8: the seek detects
breakaway when its integrated vz passes `LIFT_VZ` and then subtracts a fixed `LIFT_LAG_US` to
recover the true hover throttle, so the fake only learns its own hover point back if its acc
response builds vz over about that much of the ramp. Detection lag goes as `1/sqrt(gain)`; at gain
3 it detected ~97 us late against a 60 us correction, a 37 us standing excess = a permanent climb,
and the policy then held station wherever its output crossed the fake's hover instead of at the
setpoint (0.60 m when told 0.20 m). At gain 8 the anchor lands on 1412 against a 1410 hover point.

**Crude physics is fine in a rehearsal harness. INCONSISTENT physics silently invalidates it** —
and the failure mode is not a wrong number, it is a rehearsal that cannot exercise the thing it
exists to exercise.

**Defect 2 — `sim_vs_real` graded the pilot's own land-out as policy divergence.** First clean
flight reported **DIVERGENT**, `a_thr` MAE 2.18e-02 and worst |err| 0.71, on a path whose three
rate channels matched to 2.5e-05. All 74 divergent frames were after t=19.80 on a 21 s flight: the
LAND ramp. The policy owns thrust only in HOVER/FLIP — SEEK ramps to find liftoff, RISE holds the
learned anchor, LAND ramps down — and **the CSV recorded no way to tell those apart**, so the
offline replay diffed the pilot's own throttle profile against the policy's prediction. On a real
flight this fires every time, which means the check gating the first hardware flight was a check
that could not pass.

`phase` is now column 34 (all three `LOG_COLUMNS` copies, `_LEGACY_WIDTHS` gains 33), and
`sim_vs_real` grades only policy-commanded rows *and prints which*. Two details are deliberate:
a legacy log with no `phase` column falls back to grading everything **with that stated**, rather
than silently changing what the verdict means; and `phase` is the schema's only TEXT column, so
`load_flight` keeps it out of the numeric arrays as `FlightLog.phase` instead of coercing it to a
NaN float column — a NaN column would discard exactly the information the column was added to
carry. On a legacy header it stays the empty tuple rather than `("", "", ...)`, which is the
difference between "no phase information" and "phase information, all blank".

**Verification.** `env_check.py` PASS. `pytest` **469 passed, 1 skipped** (was 467/1 before adding
the two schema cases below). `hypergraph sync` 0 violations.

`_LEGACY_WIDTHS` listed 31 and 33 but the explicit-widths loader test stopped at 27, so neither the
raw-flow schema nor the pre-phase one — the schema every rehearsal flight recorded this afternoon —
had a test. Both added.

**Honesty / limits.** The fake's vertical model is a memoryless throttle->velocity map with no
inertia and no thrust curve, against a 25 Hz ToF on a 50 Hz loop; it settles ~0.23 m above the
setpoint and **does not reproduce the sim's 0.174 m hover**. That is a harness limit, not a result:
the rehearsal proves the *plumbing* (obs assembly, channel semantics, fused-vs-logged equality,
abort paths, schema), and the altitude behaviour is what the battery and the real flight are for.
`rad_per_count` was passed as a placeholder 0.0239 purely to satisfy the pilot's refusal-to-fly
gate — it is still unmeasured, and `modest-raven-7153` / `rapid-hill-4130` remain the blockers.

## Lineage

Parent `restless-oak-1375` (the graded 0.20 m policy this rehearses). Exercises the obs-8 deploy
path built in `snowy-brook-2829`; the `flow_lost` abort it tripped is that node's own guard firing
correctly on a drone below the sensor's working range.

## Repo

- repo: git@github.com:theo-kirby/neural-whoop.git
- branch: main
- commit: a121f78ec2c177ac87b8a9786b7dbc63316c4b7d

## State Impact

- target: lucky-lodge-5696 — the 0.20 m policy now clears every hardware-free Phase-4 precondition: selftest parity 5.01e-08 with corrective signs on vx/vy, a full WAITING->RELEASED fake flight, and sim_vs_real FAITHFUL at 1.05e-04; what remains is bench calibration, not software
- target: modest-raven-7153 — the flight log gains a phase column (schema 33->34), without which no flight CSV can distinguish policy-commanded rows from the pilot's seek/rise/land profile, and the in-flight faithfulness check cannot pass on any real flight
