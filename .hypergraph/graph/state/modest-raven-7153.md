---
node_id: a1945947-38ae-52e4-ab53-79f2b9624e1a
slug: modest-raven-7153
title: 'The real-drone deploy path: pilot flight engine, MSP bridge, and the radio link'
created_at: '2026-08-09T18:42:32+00:00'
parents:
- dusty-pine-0511
summary: 'The offboard deploy path — stdlib pilot engine, XIAO ESP32-S3 MSP bridge, Betaflight on an Air65 II, driven from the Studio Real tab. BROKEN: the last flight session ended in a tumbling crash, the airframe needs rewiring and the bench is down, and the in-flight latency tail the ESP-NOW rebuild was meant to fix is back at the WiFi baseline.'
---
Status: open

## Current

**Not `broken` — the author's own call** [rec: golden-banner-2676]**.** The spine holds: the radio-owned safety interlock, faithful thrust telemetry, and the `--bridge fake` headless tests. What does not yet hold is a settled hover on the real airframe, and that is the frontier being worked rather than damage to repair before work resumes. The tumbling crash, the stale attitude frames and the airframe rewiring all stand as measured.

The path [rec: rapid-meadow-0957] is: policy on the host, through `neural_whoop.pilot` (a stdlib-only,
steppable flight engine extracted from `scripts/pilot.py`), over MSP to a XIAO
ESP32-S3 bridge on the drone, into Betaflight on a BetaFPV Air65 II. The Studio's
**Real** tab is the always-on dashboard for it, with an opt-in parallel CPU-torch sim
of the same policy flying beside the real drone.

**The safety interlock is the design's spine and it holds** [rec: snowy-heart-2157]**.** The software Start only
sets the flight clock, and is enabled only when telemetry shows ARMED *and*
MSP-OVERRIDE engaged on the radio. The radio owns enable and instant kill; software
never writes arm or aux; stopping the RC stream is the only stop. A `--bridge fake`
mode runs the whole dashboard with no hardware and backs the headless tests.

**Why this is `broken` and not `working`:** the most recent real session (three
`hover_tof` flights at 0.7 m over ESP-NOW) got clean 3.3 s hover windows at about
2.8 degrees median tilt and faithful thrust telemetry, but none of the three settled;
all oscillated vertically, and flight 3 departed at about 6.4 s into a tumbling crash
with visibly stale attitude frames during the departure. The airframe needs rewiring
from the crash damage and the bench is down [rec: broken-fire-4858]. In-flight link
in that session: median 22-23 ms but p99 123-226 ms with up to 9.3% of frames over
100 ms — no better than the old WiFi baseline of 122-232 ms.

## Negative knowledge

- [scope: the 100-650 ms WiFi-bridge stalls | confidence: high | evidence: winter-sun-6292] The I2C-timeout hypothesis was refuted by instrumenting instead of hypothesising. `bridge_loop_max_ms` measured 1-13 ms across eight flights with motors spinning while `obs_age_ms` hit p99 122-232 ms, and the host control loop held 23-25 ms dt through every stall tick. Both endpoints healthy; the packets simply were not arriving. WiFi modem sleep, the status block and `fc.readBytes` were each refuted the same way.
- [scope: hardware bring-up on this rig | confidence: high | evidence: icy-base-2242, young-tree-5511] Four separate physical faults have presented as software faults: a longer ToF harness that stopped ACKing at 400 kHz and needed 100 kHz, a 'dead UART pin' that was a T1-to-ground solder bridge, a stale compiled-in MAC that had the drone bridge replying to itself after a board swap, and a D5/D6 solder bridge. On this rig, discriminating probes beat hypotheses.
- [scope: bench measurement as a proxy for in-flight behaviour | confidence: high | evidence: tiny-glitter-0842] The bench loop ceiling is about 5 ms and the same-day bench measurement could not reproduce the ~200 ms stalls the flights showed on 5% of ticks. Motor EMI on the I2C harness, the in-flight RF environment and BEC current draw remain the standing candidates. A bench-green link is not evidence of an airborne-green link.

## Provenance

- broken-fire-4858 — the most recent flight session, its clean windows, its crash, and the link regression
- winter-sun-6292 — the stall localisation and the refuted endpoint hypotheses
- icy-base-2242 — the rewire bring-up faults
- young-tree-5511 — the board-swap bring-up faults
- tiny-glitter-0842 — the bench-versus-flight discrepancy that is still open
