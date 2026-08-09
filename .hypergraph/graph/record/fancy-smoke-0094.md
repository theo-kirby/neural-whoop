---
node_id: 01021d40-60e2-52b6-a3de-368125796f45
slug: fancy-smoke-0094
title: d50var_s8 props-off deploy check GREEN + yaw obs sign REFUTED — Air65 II bench 2026-07-07
created_at: '2026-07-07T10:18:29.800308+00:00'
parents:
- broken-wildflower-8398
- delicate-credit-2979
summary: 'First bench execution of the campaign-close handoff: props-off deploy check of d50var_s8 (broken-wildflower-8398, ★ studio-baseline) on the real Air65 II over the WiFi bridge. GREEN on all checks — selftest forward-pass parity 4.6e-08, tilt corrections correct (tilt-right→roll_us 1178, nose-down→pitch_us 1079), and level-still commanded throttle 1409 ≈ the 1410 µs hover anchor (the amplitude-DR trim fix confirmed on hardware, vs the old flagship''s ~12% sink needing +0.06 trim). Two findings vs the sim contract: (1) the one doc-derived observation sign — yaw r = −gz — is REFUTED by the clockwise-spin check (CW-from-above read gz NEGATIVE; r now takes no flip, verified: CW spin integrates −359° and the policy counter-commands left); this board''s gyro z is inverted vs the textbook BF convention, same pattern as pitch. Commanded-yaw sign through the FC stays unverified → fly keeps --yaw center. (2) MSP_RAW_IMU serves gyro ZEROS until Betaflight boot-calibration finishes → ops rule: leave the drone still ~5 s after plug-in or the policy sees rates≡0. Link re-measured at the flying spot: median 19.9 ms RTT, p99 35–54 ms, rare ~520 ms spikes (vs 2.41 ms on 2026-07-05 — RSSI-dependent; still inside the 300 ms freshness window, consistent with the modeled p50 24 ms). Calm motors-off gyro floor sd≈0.007 rad/s, lag-1 ρ 0.62–0.81 (colored, as the DR assumes). Commit 48b630d. Verdict: cleared for the calm-air first flight.'
origin:
  backend: flywheel
  node_id: 01021d40-60e2-52b6-a3de-368125796f45
  slug: fancy-smoke-0094
  revision: 5
  exported_at: '2026-08-09T18:23:28+00:00'
---
# d50var_s8 props-off deploy check + yaw-sign refutation (bench, Air65 II)

**Hypothesis / purpose.** Execute the deploy box's side of the campaign-close handoff (`delicate-credit-2979`): before trusting `d50var_s8` (`broken-wildflower-8398`) in a real hover, run the mandatory props-off deploy check and validate the two bench-checklist unknowns (link age, calm gyro amplitude/ρ). Confirm the export is deploy-correct and every commanded sign points the right way.

## Setup
- Hardware: Air65 II (BTFL 26.6.0, MSP API 1.48) + XIAO ESP32-S3 WiFi bridge on the LAN; pure-`python3` offboard path (no CUDA venv on the Mac).
- Policy: `runs/hover_blind_air65_d50var_s8/policy_weights.json`, obs-5 × obs_stack 8 → input 40, [64,64], act-v2. No vz channel, no action echo (the s8a echo arm was RED).
- Procedure: `pilot.py selftest` (offline parity) → link `latency` (4×500) → 30 s calm motors-off gyro capture → props-off maneuver capture (level / tilt-right / nose-down / CW spin) feeding the deploy-exact forward pass.

## Results (vs the sim2real contract)
- **Selftest:** forward-pass parity worst 4.6e-08 vs the deploy-exact reference outputs; sign hints OK.
- **Trim (the headline hardware confirmation):** level-still commanded throttle **1409 µs ≈ the 1410 µs bench hover anchor** — the amplitude-DR trim fix holds on hardware. The pre-d50var flagship sank ~12% here and needed a +0.06 act[0] trim; d50var_s8 needs ~0.
- **Attitude corrections:** tilt-right → roll_us **1178** (roll-left correction); nose-down → pitch_us **1079** (nose-up correction). Both correct-signed, monotonic.
- **Yaw sign — REFUTED & fixed (Δ vs contract):** the one remaining doc-derived sign, `r = −gz` (marked UNVERIFIED in `obs_from_msp`), fails the clockwise-spin check. A CW-from-above spin read **gz NEGATIVE** (sim r peaked −4.42 rad/s, integrated **−359°** over one turn) and the policy counter-commanded left — internally consistent, so the fix is a straight sign flip: **`r = +gz`** (no flip). This board's gyro-z is inverted vs the textbook Betaflight yaw-right+ convention — the *same* inverted pattern already found for pitch. Commanded-yaw sign *through the FC* is still unverified, so `fly` keeps its `--yaw center` default.
- **Gyro-calibration gotcha (Δ vs expectation):** `MSP_RAW_IMU` returns gyro **zeros** until Betaflight's boot gyro-cal completes; handling the drone at plug-in defers cal indefinitely and the policy would fly on rates≡0. Two captures were wasted on this before the capture script was made to wait for a live gyro. **Ops rule: leave the drone still ~5 s after battery plug-in.**
- **Link (bench-checklist item 1):** median **19.9 ms** RTT, p90 23.7, p99 **35–54 ms**, rare ~520 ms spikes over 2000 requests at the flying spot — higher than the 2.41 ms median measured 2026-07-05 (RSSI/location-dependent) but inside the 300 ms freshness window and consistent with the modeled obs-age p50 24 ms. Full age *histogram* still TODO (the DR jitter weights remain percentile-approximated).
- **Calm gyro (bench-checklist item 2):** motors-off, 50 Hz, 1500 samples: sd ≈ **0.0072/0.0076/0.0023 rad/s** (x/y/z), lag-1 **ρ 0.81/0.77/0.62** — strongly colored, matching the DR's colored-noise assumption. This is the *motors-off* floor; the props-on vibration amplitude (the number that sets the operating point on the survival curve) still needs an armed capture.

## Verdict / honesty
**GREEN — cleared for the calm-air first flight.** The export is deploy-correct and the amplitude-DR trim is confirmed on real hardware. One real bug caught and fixed (yaw obs sign) that would have corrupted any policy-yaw flight. Honesty: (1) only the *observed* yaw sign is verified, not the commanded one — `--yaw center` stays. (2) The apparent "link dropouts" mid-session were the operator unplugging the battery between tests (overheat caution), not a link fault — no reliability problem exists. (3) Calm gyro is motors-off; the deploy-relevant props-on amplitude + the link age histogram are still open bench items. (4) No flight yet — this validates the seam, not flight behavior.

## Lineage
Parents: **delicate-credit-2979** (campaign close — this executes its bench handoff) and **broken-wildflower-8398** (the d50var_s8 policy under test). Commit `48b630d` (pilot yaw-sign fix + SIM2REAL bench log). Next: the first flight (`fly --takeoff --yaw center`, calm air, throttle ceiling), which will produce a flight-CSV node under this one.