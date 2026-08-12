---
node_id: 7f97bed8-d2e0-50d4-9342-32eebca5fd49
slug: shy-light-3409
title: 'The PMW3901 lands: MSP_BRIDGE_FLOW on the bridge and hover_flow — the first hover whose horizontal drift is closed-loop (integrated, uncalibrated, unflown)'
created_at: '2026-08-12T10:24:14+00:00'
parents:
- late-mud-4665
- aged-firefly-8064
- soft-breeze-8148
summary: ''
---
## What

The PMW3901 arrived and is integrated end to end, as **hardware + software only** — nothing has
been trained to a result and nothing has been flown. Two halves:

1. **Bridge (`c8f2a42`).** `firmware/xiao_bridge` gains a second downward sensor: a header-only
   SPI driver (`include/pmw3901.h`) on D8/CLK + D9/MIS + D10/MOS + D3/CS, and a bridge-local
   MSP v1 cmd **193** (`MSP_BRIDGE_FLOW`) answered locally and never forwarded — the same
   interception pattern `MSP_BRIDGE_TOF` established, no FC config touched, and the bridge still
   boots and proxies with no sensor wired. Host side: `decode_bridge_flow`, `wrap_delta`,
   `MspClient.bridge_flow()`, `Telemetry.poll(want_flow=True)` + `Telemetry.flow_delta()`, a
   `bench.py flow` desk bring-up, and a `flow_probe` firmware env that doubles as the
   calibration rig.
2. **Task (`39d3beb`).** `hover_flow` — obs `[roll, pitch, p, q, r, height_err, vx, vy]` (8),
   channels 0–5 byte-identical to `hover_tof` — plus `configs/flow-hover.yaml` at a 0.40 m
   setpoint, and `tests/test_hover_flow.py` / `tests/test_pilot_flow.py`.

## Why

Every hover result in this lab carries the same caveat, and it is the same caveat every time:
horizontal drift is **open-loop**. `hover_blind` is open-loop in all three axes; `aged-firefly-8064`
closed the vertical one with the VL53L1X; horizontal stayed open because nothing in the obs could
see it. Desk-Hover states the cost directly — clean pure-hold drift 0.047 m, but 0.55–0.77 m under
sensor noise alone.

`soft-breeze-8148` is the sharpest reason this matters. Arm 2 attacked drift with `vxy_penalty`, a
*privileged reward proxy* for a quantity the policy could not observe, and it was NO-GO: it bought
0.047 → 0.036 m of drift and paid 98 → 311 floor exits. The lesson is that shaping against an
unobservable quantity trades margin for the metric. The flow sensor removes the premise — the
policy can now observe the velocity — so `flow-hover.yaml` deliberately keeps `vxy_penalty: 0`.
Adding it back would confound the one result this config exists to produce, and it is named as
the natural arm 2 instead.

This also realizes `late-mud-4665`, the design node that predicted the exact error structure
(dropout over low-texture floors, height-coupling via the ToF, scale error, estimator latency),
with one deliberate deviation recorded under Method.

## Method

**The wire format is cumulative and non-destructive**, which was the main design decision. The
reply carries running count sums since boot plus the bridge's own millisecond stamp of the newest
sample, and the host differences two replies. A "counts since you last asked" reply is smaller and
wrong: it makes every read destructive, so one dropped packet silently eats real motion, and a
second client (a `bench.py flow` window open beside a flight) steals it. Differencing is
idempotent, and `dt` then comes from the *bridge's* clock — dividing counts by a host-jittered
interval is exactly how a clean flow signal becomes a noisy velocity. `wrap_delta` handles both
counter rollovers; a bridge reboot resyncs rather than reporting a 49-day interval.

**The PixArt init sequence was fetched, not recalled.** It is transcribed verbatim from Bitcraze's
MIT-licensed Arduino driver. Worth recording: a summarizing fetch of crazyflie-firmware's copy
returned a sequence differing in four places (`0x74`, and three writes on pages `0x14`/`0x15`).
The values are proprietary and undocumented, so they are copied and must not be "tidied".

**Three structural error terms in `hover_flow`**, each a way the channel is *wrong* rather than
merely noisy:
- **Height multiplies straight into the velocity scale.** `v = counts/dt · rad_per_count · height`,
  and the host has only `h_meas`, so the sim scales true velocity by `h_meas / z`. Free, because
  `hover_tof` already tracks the ToF hold state.
- **Below 0.08 m the sensor is blind** (PMW3901 working range — an optical limit, not a noise floor).
- **A featureless floor returns no motion at full frame rate**, which no freshness check can catch.
  Hence an explicit dropout term, and `squal` decoded on the wire rather than folded into `valid`.

Blind handling is **grace-then-fade to zero, not hold**, mirroring the deployed
`--tof-blind-grace/--tof-blind-fade` guard. An indefinitely held velocity is the same
confidently-wrong-held-channel shape as the `lucky-lodge-5696` crash mechanism; a faded velocity
decays to an honest neutral, so the fade costs nothing.

**Deviation from `late-mud-4665`:** that design put the flow-velocity error in `randomization.py`
as a DR seam, the velocity counterpart to `DetectorNoise`. It went **in-task** instead, following
`hover_tof`'s precedent — the structural terms (height coupling, range/tilt validity, dropout,
grace-fade) are estimator *structure*, not noise, and `randomization.py`'s per-channel additive
noise/bias cannot express a multiplicative scale error. Only the additive noise rides DR. If a
second flow-consuming task appears, this is the thing to factor out.

**Why 0.40 m, and why not Desk-Hover's 0.10 m.** The setpoint is forced by three constraints at
once, not chosen: the 0.08 m blind floor below; the velocity scale error in the middle (the
measured +23.9 mm ToF static offset is **24%** of a 0.10 m setpoint and **6%** of a 0.40 m one);
and the VL53L1X's 1.3 m ceiling less the measured ~0.37 m climb overshoot above (0.40 + 0.37 =
0.77 m, still 1.7× inside). 0.40 m is the widest margin available on all three simultaneously.
Consequence stated in the config: this is **no longer a desk operating point** — a fall from
0.40 m is a real crash, so it wants a floor and a mat, not the bench.

Verification: `pio run` green on all three firmware targets (`xiao_bridge`, `xiao_bridge_espnow`,
`flow_probe`); `uv run pytest` **439 passed, 1 skipped**; `scripts/env_check.py` PASS;
`configs/flow-hover.yaml` smoke-trained end to end (512 envs / 295k steps, `runs/flow-hover-smoke`,
gitignored) purely to prove the wiring loads — **not a result**.

## Result

Shipped and verified in software; **unmeasured against hardware**.

A test caught a real bug worth recording: `HoverFlowTask.setup` initially overwrote the parent's
`_p_update`, which is `hover_tof`'s **ToF** refresh probability — silently running the *height*
channel at `flow_rate_hz` (50 Hz) instead of the hardware-measured `tof_rate_hz` (25 Hz). That is
precisely the error class the 2026-07-30 sensor characterization exists to prevent, arriving by a
different route: not an optimistic constant, but a name collision through inheritance. Renamed to
`_flow_p_update`, and `test_height_scales_the_velocity_estimate` is what surfaced it.

New metric `flow_valid_rate`, and it is not decorative: a policy can post a fine `mean_xy_error`
while flying most of an episode on a faded-to-zero channel — an open-loop policy wearing a
closed-loop metric. Any arm whose no-DR `flow_valid_rate` is not ~1.0 is reporting something else.

**Open calibration debt, four constants.** `flow_rate_hz`, `flow_dropout_prob`, `flow_scale_frac`
and `flow_gyro_residual` are placeholders. `rad_per_count` — the constant the whole velocity
conversion rides on — is not in the repo at all, because it is a property of *this* lens at *this*
standoff and must be measured (`pio run -e flow_probe`: known height over a printed page, slide
100 mm, `rad_per_count = distance / (height · counts)`, repeated at a second height to agree).
This is the same debt the ToF carried between 2026-07-13 and 2026-07-30, and that one found the
nominal rate optimistic by **1.6×**.

**The intended next step is a PASSIVE flight**, not a `hover_flow` flight: fly a shipped
`hover_tof` policy with flow logged but *not* in the obs, and let the logs set those constants
before any policy consumes the channel. Note the standing blocker — `modest-raven-7153` has the
deploy bench down awaiting a rewire, and this adds a second sensor harness to that rewire rather
than removing one. `rapid-hill-4130`'s ToF zero-offset calibration also gains weight here: it was
already the named blocker for a Desk-Hover flight, and now the same offset propagates directly
into the velocity scale.

ROADMAP #9's Plan B (raw counts + ToF + gyro in obs, DR over flow-scale/dropout) is untouched and
is the natural second arm; `flow_scale_frac` already exists for it.

## Repo

- repo: git@github.com:theo-kirby/neural-whoop.git
- branch: main
- commit: 39d3bebf08128407ed3c92ccfcabb233b582b977

## State Impact

- target: modest-raven-7153 — the bridge gains a SECOND downward sensor and a second bridge-local MSP id (193, MSP_BRIDGE_FLOW, cumulative non-destructive counts); host path gains Telemetry.flow_delta + bench.py flow + the flow_probe calibration firmware. Adds a second sensor harness to the pending rewire rather than removing one; nothing measured against hardware yet.
- target: cold-pebble-7468 — task registry gains hover_flow (obs 8: hover_tof's six channels + body-frame vx,vy), configs/flow-hover.yaml at a 0.40 m setpoint, tests/test_hover_flow.py. Registered and smoke-trained only; no policy trained to a result.
- target: long-mountain-5811 — a second deploy-honest obs layout extending hover_tof's, and a recorded deviation from late-mud-4665: the flow error model went IN-TASK rather than into randomization.py as a DR seam, because the structural terms are estimator structure and a multiplicative scale error cannot be expressed by per-channel additive noise/bias.
- target: NEW optical-flow-calibration — optical flow is integrated in firmware, host and sim but UNCALIBRATED and UNFLOWN. rad_per_count is not in the repo (it is a property of this lens at this standoff and must be measured with flow_probe); flow_rate_hz, flow_dropout_prob, flow_scale_frac and flow_gyro_residual are placeholders. Same debt shape as the ToF's 2026-07-13 to 2026-07-30 gap, which found the nominal rate optimistic by 1.6x. Intended next step is a PASSIVE flight logging flow without it in the obs.
- target: rapid-hill-4130 — the ToF zero-offset calibration gains weight: the same +23.9 mm offset now propagates directly into the flow velocity SCALE (24% velocity error at a 0.10 m setpoint, 6% at 0.40 m), which is what forced hover_flow's operating point to 0.40 m.
