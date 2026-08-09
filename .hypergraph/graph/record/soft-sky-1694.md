---
node_id: 42ceffce-2ad5-58dc-8701-00451e5397c5
slug: soft-sky-1694
title: 'FIRST REAL BLIND FLIP (1/6): full 366° roll + recovery + landing — but 3 stalls parked inverted at idle throttle expose a zero-collective rate-authority sim2real gap (suspect AIRMODE off)'
created_at: '2026-07-12T17:35:20.624834+00:00'
parents:
- morning-cloud-8841
- shiny-violet-1747
summary: 'First real-hardware blind-flip session (8 flights, one-press Bench Flip): 877101 completed a FULL +366° roll with recovery, stable hover and landing — the first real blind flip — but only 1/6 attempts. Three flights share an identical stall signature: the policy rails thrust to idle near inversion (trained habit — sim rate control is collective-independent) and the real FC produces zero torque at us_thr=1000, parking the drone inverted at roll 180±2° with the roll command railed until it falls. One over-rotation (+1.76 rev) traces to the session''s worst link-staleness burst (36% stale frames in-window). Two other crashes were pre-flip hover tumbles, not flip failures. Primary suspect: AIRMODE off — enable it before session #2; durable fix: thrust-coupled rate authority + DR in sim, retrain.'
origin:
  backend: flywheel
  node_id: 42ceffce-2ad5-58dc-8701-00451e5397c5
  slug: soft-sky-1694
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: b102ada8-f826-51b1-834a-7c63e2f98e17
  slug: still-wind-1782
  revision: 0
  pushed_at: '2026-08-09T21:28:18+00:00'
  content_sha256: 93d70e7d54c49a9f8a5b39edf2f5a885306ea701f152f4bafa2e87ac1de219ea
---
# Real-drone blind-flip session #1 — Air65 II, one-press Bench Flip

**Hypothesis.** None — a characterization session: first real-hardware attempts of the blind take-off→flip→hover flight (flip-as-starter, `morning-cloud-8841`) flying the 400M-step roll acro policy (deploy parity 1.25e-07).

**Setup.** 8 flights, 2026-07-12 19:24–19:26, Bench dashboard one-press Flip (takeoff → auto-flip 1 s into hover → keep hovering), Air65 II over the XIAO MSP bridge, hover policy `d50var_s8`, acro policy `runs/acro_flip` (roll axis, Φ=2π). CSVs `runs/pilot/flight_17838770*–772*.csv`; per-flight flip windows extracted by the flip-entry action signature (a_wx≥0.99 ∧ a_thr≤−0.99).

**Results (6 flip attempts + 2 pre-flip hover tumbles).**
- **877101 — THE FLIP: cumulative roll +366° in ~0.65 s (p ≈ 12 rad/s through inversion), scrappy 1 s re-tumble, hover policy caught it, then clean hover (tilt <15°) and normal landing.** First complete blind flip on real hardware.
- **877153 — graceful bail:** rolled to 160°, thrust-dump at inversion → rotation collapsed, fell back the way it came, hover save at ~8° and a clean landing.
- **877132 / 877057 / 877203 — identical stall signature:** spin-up is healthy (p up to 24.7 rad/s) *only while thrust is up*; the moment the policy rails a_thr=−1 (us_thr 1000) near inversion, p collapses to ≈0 within one tick and the drone PARKS at roll 180±2° for 0.5–0.7 s with us_roll railed at 1998 doing nothing → falls inverted → crash-abort (detector correctly re-armed post-window). Also visible at flip ENTRY: the opening move (full rate + full thrust-cut) produces ~zero rotation for 0.2–0.5 s until the policy raises thrust.
- **877037 — over-rotation tumble:** worst link window of the session (36.5% of flip-window frames >60 ms stale, bursts to 135 ms). Held actions stretched the entry unload; when rotation finally started it hit 21 rad/s and carried +1.76 rev; window expired mid-tumble → crash-abort.
- **877078 / 877181 — not flip failures:** hard pitch-down dives into tumbles during plain hover BEFORE any flip command (877078 then sat against an obstacle at ~100° tilt for 3 s, self-righted, and completed the flight). Hover-drift/collision, tracked separately from the flip mechanism.

**Mechanism (the sim2real gap).** DiffAero's CTBR rate controller tracks body-rate commands independent of collective, so the trained policy freely rides **zero thrust** through the ballistic half of the maneuver. Real Betaflight **without AIRMODE has no mixer authority at idle throttle**: no torque to start or sustain rotation at us_thr=1000. Every stall is exactly this; the one success (877101) is the flight where rotation was already at ~12 rad/s with altitude in hand when the dump came — momentum carried it through. Aggravator: link staleness bursts (up to 36% stale in-window) hold the last action and blind the phi clock (dt-capped gyro integration) → the 877037 overshoot.

**Verdict / Honesty.** The system-level design works end-to-end on hardware — one press, take-off, learned flip, hover recovery, landing — **but 1/6 completion is not an arm**. The dominant failure is a *deploy-environment* gap, not a policy defect: (1) **check/enable AIRMODE** on the Air65 II (zero code, standard acro practice; restores rate authority at idle — addresses all 3 stalls AND the entry dead-time); (2) altitude margin is thin — the ballistic phase eats ~0.5–1 m and these hovers sit low; (3) durable sim-side fix: couple rate authority to collective in WhoopDynamics (+DR over it) and retrain — hypothesis for the 5090 loop. Not claimed: reliability, pitch-axis, repeatability.

**Lineage.** Parents: `morning-cloud-8841` (flip-as-starter method flown here) + the roll acro_flip training node (the policy that flew). Artifacts: 6-flight comparison figure (roll / gyro p / throttle+link-age, flip-aligned), per-flight metrics CSV, run.json. Commit `c98b4e11dcff` (the method); flight CSVs in-repo.