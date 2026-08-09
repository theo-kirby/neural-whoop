---
node_id: 4bce904b-6e4b-5396-bc70-d84fb66e6cb1
slug: sparkling-shadow-2507
title: 'TinyPolicy → C export measured: 79 KB flash / 1 KB RAM / ~0.55 ms on the Air65 II''s own STM32G473 — onboard compute is trivially feasible'
created_at: '2026-07-02T10:11:27.349535+00:00'
parents:
- summer-boat-5684
summary: 'O-0 gate GREEN: the real gate_race_air65 policy exports to dependency-free C with 4.8e-7 parity, needs 79.3 KB flash / 1.0 KB RAM on Cortex-M4, and projects ~0.55 ms/inference (~0.5% CPU @100 Hz) on the Air65 II''s own STM32G473 — refutes the ''RAM-tight'' deferral; flash-next-to-Betaflight and obs sourcing are the real constraints. scripts/export_c.py @ f618b12.'
origin:
  backend: flywheel
  node_id: 4bce904b-6e4b-5396-bc70-d84fb66e6cb1
  slug: sparkling-shadow-2507
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Hypothesis
None — characterization gate for the onboard-compute track (O-0): does the real deployed policy actually fit MCU-class hardware, and is the SIM2REAL.md "RAM-tight on the G473" assumption right?

## Setup
`scripts/export_c.py` (commit f618b12): exports any TinyPolicy checkpoint to one dependency-free C file (const weight arrays + float32 forward, tanh hidden, clamp[-1,1] output — the puffernet pattern tensaur/drone proved onboard a Crazyflie STM32F405 at 100 Hz) plus a harness with 32 torch-generated test vectors baked in. Run on the real `runs/gate_race_air65/ckpt_final.pt` (obs14→128→128→4, the sim2real-faithful policy from blue-unit-1398). Host build: gcc -O2. Cross-compiles: zig cc -O2, arm-linux-musleabihf, -mcpu cortex_m4 / m7 / m33 (thumb2 code, musl tanhf statically resolved), sections via GNU size.

## Results
- **Parity vs torch: max abs err 4.8e-7** over 32 random vectors (deploy semantics incl. output clamp) — criterion <1e-5 met with margin.
- 18,948 params / 18,688 MACs / 75.8 KB float32 weights.
- **Cortex-M4: 79.3 KB text (code+weights+tanhf), 0 data, 1.0 KB bss.** M7: 79.1 KB. M33: 79.3 KB.
- Host x86: 8.4 µs/inference.
- Projected (conservative ~90–100k cycles in-order, incl. ~260 software tanhf): **STM32G473 (the Air65 II's own FC, 170 MHz M4F): ~0.55 ms/inference ≈ 0.5% CPU at 100 Hz**; RP2350 ~0.7 ms; ESP32-S3 ~0.4 ms; Teensy 4.0 (600 MHz M7) ~0.08 ms. All ≥140× headroom at 100 Hz.
- Int8 option: ~23 KB total flash if float32 doesn't fit beside Betaflight.

## Verdict / Honesty
**GREEN as a measurement: compute is nowhere near the constraint — the SIM2REAL.md "RAM-tight (Neuroflight needed an H7)" deferral rationale is refuted for this policy class** (1 KB RAM vs the G473's 128 KB; Neuroflight's constraint was a different architecture/era). The binding constraints are (a) flash headroom next to a Betaflight build on the 512 KB G473 — unmeasured, staged as O-2 (build the Air65 II target and check) — and (b) where the obs vector comes from (perception stays offboard until a camera deck; velocity needs the flow estimator). Latency numbers are analytic projections from MAC counts, not on-chip measurements (no MCU in hand; no qemu on this box) — the ≥100× headroom conclusion is robust to even a 5× estimation error. LSTM/minGRU variants (system-ID idea from the PufferLib pass) would add ~4× the hidden-layer cost — still trivial.

## Lineage
Child of the onboard-compute control (summer-boat-5684). Policy under test = blue-unit-1398's gate_race_air65 checkpoint. Pattern source: tensaur puffernet (long-fog-2207 idea #8). Artifacts: results summary, generated tiny_policy.c + test_main.c.