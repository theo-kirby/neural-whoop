---
node_id: 20f5261f-1084-5832-8de9-7f2b545f9d7c
slug: polished-band-7171
title: 'Wobble decomposition: the "super wobbly, shaky, non-stationary" hover = a 2.5 Hz delay limit-cycle + latency-tail excursions + blind-policy drift with a consistent +2.5° pitch trim bias'
created_at: '2026-07-10T20:57:23.073542+00:00'
parents:
- lively-cell-6933
summary: 'Pilot''s subjective report on the parent session''s flights (lively-cell-6933): ''super wobbly, shaky, non-stationary''. Analysis over the same 7 CSVs decomposes this into THREE separate measured phenomena. (1) SHAKE: a 1.8–2.5 Hz pitch limit cycle in 6/7 flights — even hero flight 610''s ''stable'' 9 s window oscillates at 2.51 Hz, ±2.5° p2p, q spiking to 93°/s (roll far cleaner: sd 0.38° vs pitch 1.14°). At 2.5 Hz the 24 ms RTT alone is ~22° of feedback phase lag, and the control loop is RTT-synchronous (42 Hz because dt = link p50) — classic delay-induced oscillation; lever = 100 Hz control / ESP-side command hold (the Jul 7 prescription). Open split test on the 5090: FFT the same policy in M1-live under deploy-matched latency — sim cycles at ~2.5 Hz too ⇒ policy-inherent twitchiness (add action-smoothness reward); sim clean ⇒ pure seam. (2) EXCURSIONS: the ±20–90° transients correlate with ~150 ms obs_age bursts (parent''s finding). (3) NON-STATIONARY: architectural — obs = [roll,pitch,p,q,r]×8, zero translational feedback, so station-keeping is impossible in principle; AND all 7 flights settle at a consistent POSITIVE policy-view pitch equilibrium (median +1.1 to +4.2°, typically +2.5°, nose-down) with roll ≈0 — a systematic craft trim, so the drone marches directionally rather than wandering (CSV logs policy-view obs, so this is the policy''s own settled equilibrium, floor-level-referenced). Mitigations: level trim exposed in the Bench UI (commit 60147b2; dial opposite the drift, start ≈ −2.5° pitch); real fix = velocity obs: a bare PMW3901 (CJMCU-3901, SPI, no ToF) is ORDERED — plan is flow × assumed-hover-height → vel_body under flow-scale DR (±~40%) per ca2598a4, XIAO wiring on fresh matrix-routed SPI pins, VL53L0X ToF later for metric height (051be7dc). Sim seam + hover_flow training can start on the 5090 before hardware arrives.'
origin:
  backend: flywheel
  node_id: 20f5261f-1084-5832-8de9-7f2b545f9d7c
  slug: polished-band-7171
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 0bca8d09-7d41-503d-a59c-a5472c0bdca6
  slug: delicate-fog-4007
  revision: 0
  pushed_at: '2026-08-09T21:28:03+00:00'
  content_sha256: 01eac00d6734e42828ad24b095ebcb406ea0997e274440dd34fd9a8f5348891c
---
# Wobble decomposition — what "super wobbly, shaky, non-stationary" actually is

**Trigger.** After the parent session (lively-cell-6933), the pilot's honest read: the hover is still *super wobbly and shaky and non-stationary* — pushing back on the '9.0 s stable window @ 2.2°' headline. The pushback is fair: the medians hide structure. Analysis over the same 7 flight CSVs splits the complaint into three separate, separately-attackable phenomena.

## 1. Shake = a 1.8–2.5 Hz pitch limit cycle (6/7 flights)
- Hero flight `610`'s "stable" window: pitch oscillates at **2.51 Hz**, ±2.5° p2p (sd 1.14°), **q spikes to 93°/s**. Roll is far cleaner (sd 0.38°) — the cycle is pitch-dominant.
- At 2.5 Hz, the 24 ms link RTT alone is ~22° of feedback phase lag; the tail bursts are far worse. And the control loop is **RTT-synchronous** — it runs 42 Hz precisely because dt = link p50. Classic delay-induced oscillation.
- **Lever:** decouple command rate from telemetry RTT — 100 Hz control / ESP-side command hold / MSP oversampling (the Jul 7 session's prescription, aged-wildflower-8839). Same axis as the excursions.
- **Open split test (5090):** run this policy in M1-live with deploy-matched latency and FFT the pitch. Sim also cycling ~2.5 Hz ⇒ the noise-hardened policy is inherently twitchy → action-smoothness reward term. Sim clean ⇒ pure seam gap.

## 2. Wobble excursions = the latency tail
The ±20–90° transients correlate with ~150 ms obs_age bursts (parent's flight-739 finding). Same lever as #1.

## 3. Non-stationary = blindness + a consistent trim bias
- **Architectural:** obs = `[roll, pitch, p, q, r]` × 8-stack. Zero translational feedback — the policy holds *attitude*, not *position*; drift is invisible to it in principle.
- **Measured bias:** all 7 flights settle at a **positive policy-view pitch equilibrium** — median +1.1…+4.2°, typically ≈ +2.5° (nose-down convention) — while roll sits ≈0. The CSV logs the policy-view obs (post level-reference), so this is the policy's own settled equilibrium. A consistent sign means the drone doesn't wander — it **marches**.

## Mitigations (shipped / planned)
- **Shipped (commit `60147b2`):** the engine's existing level trim (`trim_pitch_deg` → obs offset, controller.py:439) is now exposed in the Bench UI, riding the Start params message. Dial opposite the drift between hops; starting point ≈ **−2.5° pitch** for a forward march. A knob to tune in flight, not a derived constant.
- **Ordered:** a bare **PMW3901** (CJMCU-3901, SPI, no ToF). Plan: flow × assumed-hover-height → `vel_body` obs under **flow-scale DR** (±~40%, absorbing the missing height sensor) per the ca2598a4 flow-velocity seam design; wire to the XIAO on fresh matrix-routed SPI pins (D9/D10 now carry the FC UART; avoid dead-input D7/GPIO44); a $4 VL53L0X ToF later upgrades to metric height (051be7dc). With velocity obs, even the trim bias self-corrects — the policy sees itself translating.
- **Sequencing:** the sim-side flow seam + `hover_flow` training runs on the 5090 and needs no hardware — it should be training before the sensor arrives.

## Verdict / honesty
Measurement — no hypothesis resolved. Sharpens the campaign's residual into two axes: the **link tail** (shake + excursions — seam work) and **translational blindness** (drift — sensor + task work). Honesty: the 2.5 Hz policy-vs-seam attribution is untested until the M1-live FFT; the drift-direction ↔ trim-sign mapping should be confirmed against what the pilot observes on the floor before trusting the −2.5° starting point; single session, calm air.

## Lineage
Parent: **lively-cell-6933** (the flight session whose CSVs this decomposes). The latency thread: **delicate-credit-2979**, **aged-wildflower-8839**. The flow path: **051be7dc** (camera/ToF decision), **ca2598a4** (flow-velocity DR seam design). Trim UI shipped at `60147b2`.