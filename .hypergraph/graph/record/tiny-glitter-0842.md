---
node_id: 11e0104e-7ba9-5902-8be2-121e7149e807
slug: tiny-glitter-0842
title: 'ToF characterized on hardware (5 flights): the SENSOR is healthy — 23.9 ± 2.4 mm floor, 92–99% coverage — but the deploy path around it had 3 real defects, all fixed'
created_at: '2026-07-30T19:17:57.773983+00:00'
parents:
- white-rice-3299
- aged-firefly-8064
- floral-unit-0997
summary: 'First real ToF flight data on the shipped w128u15 policy. Sensor: static floor 23.9 mm ± 2.4 mm over 629 pre-liftoff samples (per-flight sd 1.4–2.5 mm), 92–99% coverage, monotone airborne traces — GREEN, the 100 kHz rewire held. Three defects found around it, all fixed: (1) stale range × fresh attitude manufactured a 0.449 m phantom step in the policy''s obs 180 ms before a tumble; (2) the pilot applied NONE of the sim''s 45°/1.3 m validity gates, so a 0.824 m slant-range artifact at 63° pitch went straight into the obs; (3) tof_rate_hz 40 was optimistic by ~1.6× — measured 24.8–27.1 Hz fresh at the pilot, so every ladder policy trained on a fresher channel than it flies. Honesty: NO flight hovered (2 dead packs, 3 inverted), so this characterizes the SENSOR, not flight performance; and the link-stall root cause (blocking 100 ms I2C timeout) is instrumented but UNCONFIRMED until loop_max_ms is read on hardware. Commits 87abc57 / 8c05632 / d1d891b.'
origin:
  backend: flywheel
  node_id: 11e0104e-7ba9-5902-8be2-121e7149e807
  slug: tiny-glitter-0842
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
---
# ToF sensor characterization + three deploy fixes (2026-07-30)

## Setup

Five bench flights on the Air65 II, `runs/pilot/flight_1785399{004,032,079,097,119}.csv` — the
first real ToF data since the 2026-07-29 rewire (I2C moved to D5/D6, dropped to 100 kHz) and the
first flown on the shipped `hover_tof_air65_w128u15` deploy package. 4.7–17.1 s each, control loop
41–44 Hz. No hypothesis: this is a characterization pass on a channel the whole hover_tof ladder
assumed but had never measured.

## Results

### The sensor is healthy (GREEN)

| Metric | Measured |
|---|---|
| Static noise floor (629 pre-liftoff samples, all 5 flights) | **23.9 mm mean, σ 2.4 mm** |
| Per-flight σ on the ground | 1.4 / 1.5 / 1.6 / 2.2 / 2.5 mm |
| Coverage (control ticks carrying a value) | **92–99%** |
| Airborne trace | monotone, ~10 mm steps (flight …097 climbs 0.097 → 0.55 m over 1.8 s) |

No drift, no ambient sensitivity, no dependence on which pack. The 100 kHz drop + D5/D6 rewire
stuck. **This is the first evidence the ToF is a credible control input rather than a diagnostic.**

### Defect 1 — stale range × fresh attitude → a 0.449 m phantom obs step

The pilot re-ran `h = range·cos(roll)·cos(pitch)` **every control tick against the current
attitude**, so a range held across a link stall got re-projected through attitude it was never
measured with. Flight …097, t=7.285 (range frozen at 0.824 m for ~140 ms while pitch snapped
63° → 15°):

```
7.26  tof=0.824  pitch=+1.106   h_err=0.666
7.29  tof=0.824  pitch=+0.257   h_err=0.217   <-- 0.449 m jump, range never changed
7.31  tof=0.310  pitch=+0.257   h_err=0.705   <-- and back
```

The policy's height observation slammed half a metre and returned inside 45 ms. **180 ms later the
drone tumbled** (roll → 2.24 rad). Not claimed as the cause — but it is the only obs discontinuity
of that magnitude anywhere in the dataset, and it sits immediately upstream of the loss.

Fix: `Telemetry.height_sample()` returns `(range_m, sample_time)`, with `sample_time` recovered
from the bridge's own age stamp; `FlightController` corrects **once per new sample** against
`_att_at(sample_time)`. 4 regression tests, each verified to fail on the parent commit.

### Defect 2 — the deploy path applied none of the sim's validity gates

`tasks/hover_tof.py` holds past **45° tilt** and past **1.3 m slant**. The pilot applied neither.
The 0.824 m reading above was taken at 63° pitch — pure slant-range artifact (cos 63° = 0.45, true
height ~0.37 m) that the sim would have rejected outright. So the deployed policy was fed a channel
with *different semantics* than the one it trained against.

Fix: `FlightParams.tof_max_m` / `tof_tilt_limit_deg` now mirror `HoverTofConfig`. A live-but-wholly-
rejected sensor aborts on the same 1 s `tof_lost` clock as a silent one — a channel frozen by the
gate is exactly as blind as a dead sensor.

### Defect 3 — the sim's sensor rate was optimistic by ~1.6×

Measured **fresh** range rate at the pilot (distinct `tof_m` values per second):

| flight | fresh Hz | log-loop Hz |
|---|---|---|
| …004 | 24.8 | 42 |
| …032 | 20.5 | 41 |
| …079 | 26.9 | 41 |
| …097 | 27.1 | 42 |
| …119 | 25.4 | 44 |

The log loop ran 41–44 Hz, so this is the sensor/link, not the sampler. The VL53L1X free-runs at
25 ms and polling + UDP jitter eats the rest. **Every policy in the hover_tof ladder trained against
a height channel ~1.6× fresher than the one it actually flies.**

Fix: `HoverTofConfig.tof_rate_hz` default 40 → 25. Historical ladder configs keep their explicit
`40.0` so past nodes stay reproducible; the retrain is a one-factor config off the shipped baseline
(`configs/hover_tof_air65_w128u15_r25.yaml`).

### Link stalls — measured, root cause instrumented but NOT confirmed

`obs_age_ms` p50 23 ms, **p99 190–224 ms, max 250** — on ~5% of ticks (flight …032 worst, 10.2%
>100 ms). The *whole* telemetry frame freezes, attitude included, for up to 12 consecutive ticks —
so this is the bridge's `loop()`, not the ToF. These stalls sit exactly on the 200 ms staleness
reject threshold, and they are what makes defects 1 and 2 bite.

Prime suspect: `tof.setTimeout(100)` — a blocking I2C read allowed to park the whole MSP proxy for
100 ms to salvage one range sample. Magnitude matches (one or two timeouts ≈ 100–200 ms) and the
timing matches (appeared with the ToF work). Firmware now sets **10 ms**, polls at 12 ms instead of
5, drains the whole UDP burst per pass, and runs the blocking I2C **last** so it can never sit
between an inbound MSP request and its forward.

**This remains a hypothesis.** The bridge now reports its own worst `loop()` duration per 5 s window
on the USB heartbeat and as a trailing `u16 loop_max_ms` on the `MSP_BRIDGE_TOF` reply
(`bench.py --udp <ip> tof` prints it; 6-byte replies from older firmware still decode). Confirming
it means flashing the bridge and reading that number.

## Verdict / Honesty

**Sensor GREEN. Surrounding deploy path RED — three defects, all fixed. Root cause of the link
stalls: unconfirmed.** No `outcome:` tag: the result is genuinely mixed and a single verdict would
misrepresent it.

Things this node does **not** show:

- **No flight hovered.** …004 and …032 never left the ground on sagging packs (3.58→2.89 V and
  3.22→2.96 V); …079, …097, …119 all ended inverted. …097 is the only genuinely airborne one
  (~0.3–0.45 m corrected, ~2 s). This characterizes the **sensor**, not flight performance, and
  says nothing about whether the fixes improve hover.
- **Beware naive summaries of …079**, which report a 0.406 m max ToF. That is tumble garbage.
- The `tof_characterization.png` middle panel reconstructs both estimators offline; new-sample
  detection there uses value-change as a proxy, because the CSV does not carry the bridge age
  stamp. The deployed code uses the actual stamp.
- Whether 25 Hz training helps or hurts is **untested** — that is the retrain this node sets up.

## Lineage

- Parent `white-rice-3299` (DEPLOY: `hover_tof_air65_w128u15` shipped at 1.0 m) — the policy these
  flights flew, and the deploy package whose ToF path is corrected here.
- Parent *Method: measured height — VL53L1X on the bridge* — the sensor seam being characterized;
  its 40 Hz / no-gate assumptions are the ones this node measures and corrects.
- Parent *Method: hover_tof — the measured ToF height enters the obs* — the deploy contract whose
  sim↔real mismatch (defects 1 and 2) is closed here.

Commits: `87abc57` (pilot: correct once per sample + validity gates), `8c05632` (xiao_bridge: bound
the blocking I2C + `loop_max_ms` instrumentation), `d1d891b` (sim rate 40→25 + characterization
docs + retrain config).

Next: flash the bridge and read `loop_max_ms`; train `hover_tof_air65_w128u15_r25` on the 5090 and
A/B it against the shipped baseline.