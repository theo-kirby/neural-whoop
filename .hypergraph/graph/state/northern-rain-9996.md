---
node_id: 563f30bc-af0a-5192-9e2e-34af8e012426
slug: northern-rain-9996
title: Onboard compute is measured and comfortable; nothing has been ordered
created_at: '2026-08-09T18:42:33+00:00'
parents:
- modest-raven-7153
summary: 'The C export needs 79.3 KB flash and 1.0 KB RAM at 4.8e-7 parity on the Air65 II''s own STM32G473, refuting the ''RAM-tight'' deferral. Path B (a gram-class MSP companion) is the recommended first step and its deploy recipe is 3-seed GREEN in sim. BLOCKED: the ~$40-55 BOM awaits the user''s approval and nothing has been ordered.'
flywheel:
  node_id: 3b3eac35-0b26-58fd-9968-ebcc6ef276d8
  slug: super-snowflake-7200
  revision: 0
  pushed_at: '2026-08-09T21:28:39+00:00'
  content_sha256: e8f4bb518531c2cf79948f669dd05f718d6ea824a05a257d7766970b0c9ae34a
---
Status: blocked

## Current

The compute question is settled and it was settled by measurement, not projection.
The real `gate_race_air65` policy exports to dependency-free C with **4.8e-7 parity**,
needs **79.3 KB flash and 1.0 KB RAM** on a Cortex-M4, and projects about 0.55 ms per
inference (roughly 0.5% CPU at 100 Hz) on the Air65 II's own STM32G473
[rec: sparkling-shadow-2507].

Three paths were ranked in a decision doc [rec: little-term-0124]:

- **Path A** [rec: little-term-0124] — the policy inside a Betaflight fork on the G473. Zero grams and the
  end-state for racing, but a fork to maintain, unmeasured flash headroom next to
  Betaflight, and custom firmware on the only airframe raises bring-up risk. Not the
  first step.
- **Path B** [rec: little-term-0124] — a gram-class MSP companion MCU. **Recommended first**, and it also
  retires the flow-deck forwarding risk.
- **Path C** [rec: little-term-0124] — a camera / AI deck. Deferred; +18% all-up weight at the AI-deck end.

The architecture is hybrid-obs: fresh local state on the drone, a roughly 30 Hz
uplinked target channel. The env already models exactly that split
(`uplink_latency_steps` / `uplink_interval_steps`), so each path is a DR config
rather than new code. The Path-B deploy recipe of record is hybrid-obs x Muon x
reliability shaping, GREEN across three seeds at 2.32-2.54 s clean lap and 95.5-98.3%
completion [rec: muddy-mouse-2952].

**What blocks it:** the BOM (about $40-55: a Teensy 4.0 or XIAO ESP32-S3 Sense, a
PMW3901, a 1S-to-3.3 V regulator) **awaits approval and nothing has been ordered**
(`docs/ONBOARD_COMPUTE.md`). Open item O-2 — flash headroom next to Betaflight —
cannot be measured without building the Air65 II target. Three further open items
need physical boards on a scale, a Betaflight build, and a measurement of ELRS/MSP
passthrough bandwidth.

## Negative knowledge

- [scope: the 'RAM-tight' reason for deferring an onboard policy | confidence: high | evidence: sparkling-shadow-2507] Refuted. docs/SIM2REAL.md deferred the onboard firmware NN as RAM-tight, citing that Neuroflight needed an H7. For this policy class it is wrong by two orders of magnitude: 1.0 KB used against 128 KB available on the G473. Compute is nowhere near the constraint; the binding constraint is Betaflight's 512 KB flash, and int8 quantisation to about 23 KB is the fallback if float32's 79 KB does not fit.
- [scope: Muon under offboard action latency | confidence: high | evidence: muddy-mouse-2952] Muon's DR-on completion collapse (0.55-0.60) is not a property of the optimiser — it is an interaction with action latency. Under the onboard split with fresh actuation, Muon is both faster and more robust. A lever judged bad offboard can be the right lever onboard.

## Provenance

- summer-boat-5684 — the control node that opened the onboard-compute track
- sparkling-shadow-2507 — the measured flash, RAM and inference budget, and the refuted deferral
- little-term-0124 — the ranked path decision and the BOM awaiting approval
- soft-moon-6755 — the hybrid-obs split-latency retrain that removed the offboard conservatism tax
- muddy-mouse-2952 — the Path-B deploy recipe of record, 3 seeds
