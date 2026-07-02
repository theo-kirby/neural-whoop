# ONBOARD_COMPUTE.md — the onboard-policy track for the Air65 II

*2026-07-02. Companion to `docs/SIM2REAL.md` (offboard-first remains the locked first-flight
plan; this doc turns its deferred "onboard NN" milestone into a concrete, measured track).
Flywheel: `cluster:deploy-hw`, control node `summer-boat-5684`.*

## What we measured today (no hardware required)

`scripts/export_c.py` exports any TinyPolicy checkpoint to a single dependency-free C file
(puffernet pattern — the same pattern tensaur/drone proved at 100 Hz **onboard** a Crazyflie's
STM32F405 inside its firmware; see the PufferLib comparison, `docs/COMPARISON_PUFFERLIB.md`).
Measured on the real `gate_race_air65` checkpoint (obs14 → 128 → 128 → 4, tanh, clamp output):

| Quantity | Measured |
|---|---|
| Numerical parity vs torch (32 vectors) | **max abs err 4.8e-7** |
| Params / MACs per inference | 18,948 / 18,688 |
| Flash, float32 (Cortex-M4 `-O2`, zig cross-compile, code+weights+`tanhf`) | **79.3 KB text** |
| RAM (scratch activations) | **1.0 KB bss** |
| Host x86 latency | 8.4 µs/inference |

**The "RAM-tight" assumption in SIM2REAL.md is wrong for this policy class.** 1 KB of RAM is
nothing (the G473 has 128 KB). The actual pressure point is *flash*, because Betaflight already
nearly fills 512 KB parts unless built with a trimmed feature set (Betaflight manages its 512 KB
targets — F411/F722/G4 — via cloud-build feature selection). Int8 weight quantization drops the
policy to **~23 KB** (19 KB weights + code) if float32 doesn't fit next to a minimal build.

### Projected inference latency (18.7k MACs + 260 `tanhf`, conservative in-order estimates)

| Chip (where it lives) | Clock / core | Est. cycles | Latency | Headroom @ 100 Hz |
|---|---|---|---|---|
| **STM32G473** (Air65 II FC, already onboard) | 170 MHz M4F | ~90–100 k | **~0.55 ms** | ~180× (≈0.5 % CPU per call) |
| STM32F405 (tensaur's proven chip) | 168 MHz M4F | ~90–100 k | ~0.56 ms | proven in flight at 100 Hz |
| RP2350 (XIAO RP2350, ~1 g class) | 150 MHz M33F | ~100 k | ~0.7 ms | ~140× |
| ESP32-S3 (XIAO Sense, camera onboard) | 240 MHz LX7 | ~100 k | ~0.4 ms | ~230× |
| MIMXRT1062 (Teensy 4.0, ~2.4 g class) | 600 MHz M7 | ~45 k | ~0.08 ms | ~1300× |

**Conclusion: compute is nowhere near the constraint.** Every candidate — including the chip the
drone already carries — runs the policy with two-plus orders of magnitude of headroom. The
constraints that actually rank the paths are *flash headroom, integration surface, mass, and
where the observation vector comes from.*

## The obs problem is the real fork

The policy needs obs-v4: `target_rel` (perception), `vel_body` (flow fusion), attitude + rates
(FC already has these at 1 kHz+). Moving the *policy* onboard only pays if it shortens the
staleness of what it consumes:

- Attitude/rates/velocity onboard → **fresh** (vs ~40–100 ms round-trip offboard).
- `target_rel` still comes from the camera pipeline — offboard detector until Path C.

So the natural onboard architecture is **hybrid**: fast state obs sampled locally at the control
rate, slow `target_rel` uplinked at video rate (~30 Hz) and held/latency-compensated — exactly
the staleness structure our `DetectorNoise` + `action_latency` DR already trains against, but
with the delay moved off the *action* path onto only the *target* channel. That is a strictly
smaller sim2real gap than full offboard.

## Paths

### Path A — the chip we already have (STM32G473 inside Betaflight; +0 g, ~$0)
Policy compiled into a Betaflight fork as a custom task (tensaur did the equivalent as a
Crazyflie out-of-tree controller with a param-toggle PID fallback — copy that safety pattern).
- **For:** zero mass/power; obs (gyro/attitude, and flow if BF reads the sensor raw) at native
  rates; the action path becomes local (kills the dominant latency).
- **Against:** Betaflight fork + maintenance; flash headroom on 512 KB unknown until we build the
  Air65 II target (open item O-2); BF does not fuse flow→velocity (we'd port our host estimator
  into the task); custom firmware on the only airframe raises bring-up risk.
- **Verdict: the end-state for racing** (lowest latency, zero mass), but not the first step.

### Path B — gram-class companion MCU (+1–3 g, ~$15–25)
Teensy 4.0 (600 MHz M7, ~2.4 g class) or XIAO RP2350/ESP32-S3 (~1–3 g class) velcroed to the
frame: runs the policy + the flow→velocity estimator, reads the PMW3901/ToF directly (SPI/I2C),
receives `target_rel` from the host (its own 2.4 G link on ESP32-S3, or ELRS passthrough), and
commands the stock Betaflight FC over **MSP on a spare UART** — the exact seam Stage 0 already
builds for offboard.
- **For:** no Betaflight fork (stock firmware + MSP override); *also solves the flow-deck
  integration risk flagged in SIM2REAL.md* ("may need a tiny companion MCU if UART forwarding is
  messy") — one board owns flow + policy; incremental: the same MSP packets the host sends today,
  now generated onboard; trivially debuggable over USB on the bench.
- **Against:** +1–3 g on a 25 g AUW whoop (~+4–12 %, agility tax smaller than the flow deck we
  already accepted); needs a 3.3 V feed from the 1S rail; two-MCU architecture.
- **Verdict: the recommended first onboard step.**

### Path C — camera + NN companion deck (+3–5 g, $30–100)
Onboard perception: Crazyflie **AI-deck** class (GAP8 8+1-core RISC-V + Himax 320×320, **4.4 g**,
up to 300 mA — the canonical nano-drone platform, PULP-Dronet lineage) or XIAO **ESP32-S3 Sense**
(OV2640 camera, ~3 g class) running a tiny gate detector feeding the Path-B policy locally.
Removes the video downlink entirely → full autonomy, no host in the loop.
- **Against:** +18 % AUW at the AI-deck end; a whole detector-on-MCU workstream; our detector
  currently assumes host-side compute.
- **Verdict: defer** until Path B flies; XIAO ESP32-S3 Sense is the cheap probe (same board can
  serve Path B first, camera unused).

## Recommendation (staged, composing with SIM2REAL.md)

- **O-0 (done, this session):** C export + parity + size/latency budget — `scripts/export_c.py`.
- **O-1 (bench, ~$25):** Path B rig on the desk: companion board + PMW3901 + MSP into the Air65
  II from Stage 0. Same policy binary as O-0. Gate: companion reproduces the host's MSP stream
  with fresh local state obs.
- **O-2 (parallel, no hardware):** build the Air65 II Betaflight target from source, measure
  flash headroom with/without the 79 KB (f32) and ~23 KB (int8) policy → go/no-go data for Path A.
- **O-3:** hybrid-obs retrain — split latency DR (fresh state obs, 30 Hz stale target channel)
  and re-evaluate; this is the sim-side counterpart of the onboard architecture.
- **O-4 (end-state):** Path A inside Betaflight with the tensaur-style RL/PID param toggle;
  Path C when onboard perception becomes the frontier.

## BOM awaiting approval (nothing ordered)

| Item | ~Price | Purpose |
|---|---|---|
| Teensy 4.0 (no pins) **or** XIAO ESP32-S3 Sense | $24 / $14 | Path B companion (Sense also covers the Path C probe) |
| PMW3901 breakout (+ VL53L0x ToF if not combined) | ~$10–15 | flow → velocity, owned by the companion |
| 1S→3.3 V regulator breakout, silicone wire, heatshrink | ~$5 | power/mounting |

Open items: weigh the actual boards (published "gross" weights are packaging-inflated; bare
boards are ~1–3 g class); measure Air65 II BF target hex size (O-2); ELRS/MSP passthrough
bandwidth for the 30 Hz target channel; companion current draw on the 1S rail.
