---
node_id: 58f821ed-4aed-539a-8618-1c93575960cc
slug: blue-field-6813
title: 'Stage 0: actuation-seam bench bring-up — MSP CTBR injection + Betaflight rate calibration + airframe measurement'
created_at: '2026-06-29T09:45:26.209535+00:00'
parents:
- blue-mountain-7167
- bitter-fire-0679
summary: 'Hypothesis/planned first hardware step: streaming MSP_SET_RAW_RC into Betaflight (acro) with rates flattened to our linear +-12/+-6 rad/s mapping reproduces the sim RateController''s step-response within tolerance; bench-measure mass/inertia/thrust-curve/hover-throttle to pin the Mobula6 airframe. Needs only drone + USB, no perception — isolates and closes the actuation half of the gap. Tests blue-mountain-7167''s RC-channel deployment path. Not started.'
origin:
  backend: flywheel
  node_id: 58f821ed-4aed-539a-8618-1c93575960cc
  slug: blue-field-6813
  revision: 5
  exported_at: '2026-08-09T18:23:28+00:00'
---
# Stage 0 — actuation seam bring-up (bench)

**Hypothesis.** The CTBR seam can be reproduced on real hardware by sending the 4 RC channels via MSP_SET_RAW_RC in Betaflight acro mode, with BF rates flattened to our linear act-v2 mapping (+-12/+-12/+-6 rad/s) so BF's rate curve + PID inner loop matches our sim RateController. Expect the real rate step-response to track sim K_angvel=[16,16,8] within a tolerance the rate_gain DR already hedges.

**Setup (planned).** Drone + USB only; no perception, no flight (bench / tethered).
- MSP `MSP_SET_RAW_RC` injection; handle the MSP-override + failsafe interaction (BF issues #12790/#13374); keep a manual-pilot fallback.
- Calibrate BF rate curve -> linear mapping.
- Measure: rate step-response vs K_angvel, hover throttle, thrust curve / TWR, mass, inertia/arm.

**Output.** Pins the re-centered Mobula6 airframe DR + matched controller constants (feeds the sim-recenter node), and validates the deployment action path.

**Verdict.** Open / not started; the first step once hardware arrives.

**Lineage.** Child of the sim2real plan (bitter-fire-0679) and of blue-mountain-7167 (this is where its RC-channel deployment idea gets tested). Feeds the sim re-center node.