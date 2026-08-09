---
node_id: 3c00d055-0265-555b-9828-d87f570751c9
slug: morning-cloud-8841
title: 'Method: Bench Flip-as-starter — one press = take-off → flip → keep hovering (pending-flip seam in request_flip)'
created_at: '2026-07-12T16:22:38.480970+00:00'
parents:
- lively-block-9924
summary: 'One-button blind-flip flight for the bench: request_flip() while WAITING now doubles as the software Start (identical ARMED+override radio gate; no acro policy = rejected outright), arming a pending flip that auto-fires ACRO_START_SETTLE_S (1 s) into free HOVER through the existing gate-rechecking trigger seam, then hands back to the hover policy for the rest of the flight — take-off → flip → keep hovering from a single Bench Flip press. Safety unchanged (radio owns enable/kill; bounded window + crash-detector re-arm untouched). Verified: 22 pytest green (+3 new incl. a ws end-to-end), fake-bridge takeoff-mode walk WAITING→COUNTDOWN→SEEK→RISE→HOVER→FLIP→HOVER→LAND→RELEASED with rot 1.00·Φ and no re-fire. Real-drone one-press flight still hardware-gated.'
origin:
  backend: flywheel
  node_id: 3c00d055-0265-555b-9828-d87f570751c9
  slug: morning-cloud-8841
  revision: 1
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: f001f14d-59d7-5005-8770-4e847fe953fb
  slug: floral-flower-4070
  revision: 0
  pushed_at: '2026-08-09T21:28:03+00:00'
  content_sha256: 16a7caec4658a951b43c3b000a5309d4cb1f3fde6c5d0963c020385c78f87867
---
# Method: Flip-as-starter — the one-button blind-flip flight

**What & why.** The acro harness (`lively-block-9924`) required two interactions for a real-drone flip flight: press **Start** (take-off → hover), wait for HOVER, then press **Flip** inside the maneuver gate. For the actual bench test that's one press too many — the operator's hands should stay on the radio (which owns arm + kill). This node collapses it: **pressing Flip while still WAITING now *is* the starter** — take-off runs as usual, the flip auto-fires once free hover settles, and the flight then simply keeps hovering out its normal clock (LAND ramp unchanged).

**Setup (the seam).**
- `pilot/controller.py::request_flip()` while WAITING now delegates to `request_start()` — the **exact same ARMED + override-engaged radio gate** — and on acceptance arms `flip_pending`. No acro policy loaded → still rejected outright (a Flip press can never bare-Start).
- The pending flip fires through the existing auto-trigger seam: `ACRO_START_SETTLE_S = 1.0 s` into free HOVER (`t_air`, so the SEEK/RISE climb-out is excluded), re-checking **every** maneuver gate (fresh link + near-level) each tick — a not-yet-settled tick just retries. One-shot via the existing `flip_triggered`; `flip_pending` clears when the window opens.
- Bench UI (`bench.js`): the Flip button enables under the same `armed + override + waiting` predicate as Start (still enables in HOVER as before), and a WAITING press applies the panel params first, exactly like Start. `{type:"flip"}` over `/ws/flight` is unchanged wire-format.
- Safety story untouched: software still only ever sets a clock; the radio owns enable + instant kill; the bounded `acro_flip_max_s` window, crash-detector suspension/re-arm, and `flip_at_s` (CLI auto-flip) are all unchanged.

**Results.**
- **22 pytest green** across `test_flight_controller.py` / `test_flight_ws.py` / `test_pilot_acro_obs.py` (+3 new: starter-gating incl. no-acro and not-armed rejections; full one-press sequence with the settle-window timing asserted; websocket flip-from-WAITING end-to-end).
- **Fake-bridge, takeoff mode, one press from WAITING:** phase walk `WAITING → COUNTDOWN → SEEK → RISE → HOVER → FLIP → HOVER → LAND → RELEASED`, flip fired at `t_air ≥ 1.0 s`, rot 1.00·Φ, exit tilt 2°, no crash-abort, no re-fire — *take-off, flip, keep hovering* verbatim.
- CLI `--flip-at` regression on the fake bridge: unchanged (FLIP at 6 s, done 0.83 s, → HOVER → land).

**Verdict / Honesty.** Method shipped + fake-bridge-verified; **the real-drone one-press flight is still hardware-gated** (same status as the parent harness). The 1 s settle constant is a judgment call, not tuned on hardware — if the real climb-out needs longer to pass the 15° near-level gate, the retry-every-tick design just fires later (or never, degrading gracefully to a plain hover flight).

**Lineage.** Parent: `lively-block-9924` (the acro-flip harness whose Flip button + FLIP window this extends). Deploy weights for the real test staged this session at `runs/acro_flip/` (parity vs refs worst 1.25e-07). Commit `c98b4e11dcff72af850c13846f94ed0b0dd1bac1`. Stays in `cluster:agility`.