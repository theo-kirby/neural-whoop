---
node_id: fb011371-1b69-56e3-803a-5241953b497d
slug: winter-sun-6292
title: Link stalls localized to the WiFi hop — my I2C hypothesis REFUTED; both endpoints measure healthy while the air carries p99 124 ms / max 523 ms on the desk. Deploy fixes 1+2 CONFIRMED in flight (phantom steps 1→0)
created_at: '2026-07-30T20:42:10.673927+00:00'
parents:
- tiny-glitter-0842
summary: 'Follow-up to tiny-glitter-0842''s open question, settled by instrumenting instead of hypothesizing. (1) Deploy fixes CONFIRMED on hardware: 0 phantom h_err steps across 8 flights (was 1 at 0.449 m), and the ported sim gates actively rejected 11 over-range + 97 over-tilt readings that would previously have entered the obs. (2) My I2C-timeout hypothesis for the stalls is REFUTED: bridge_loop_max_ms measured 1–13 ms across all 8 flights (motors spinning) while obs_age_ms hit p99 122–232 ms, and the host control loop held 23–25 ms dt through EVERY stall tick — both endpoints healthy, packets simply not arriving. (3) Localized by splitting the RTT with the bridge-answered MSP_BRIDGE_TOF (never reaches the FC): pure air = median 11.05 / p90 33.24 / p99 124.32 / max 523.48 ms, full FC trip = 25.71 / 62.21 / 197.36 / 650.56. The FC path adds only ~14 ms median (normal UART + Betaflight scheduling); the AIR owns the tail. Measured on the desk, motors OFF — so the stalls were never flight-specific. A 45 Hz loop budgets 22 ms and the air''s p90 alone is 33 ms. This is now the top blocker; no policy holds a hover through it. Commits 670efbd / a737dc2 / 078714a.'
origin:
  backend: flywheel
  node_id: fb011371-1b69-56e3-803a-5241953b497d
  slug: winter-sun-6292
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 1d3bb60b-a310-5d90-986b-0bd1ca8e1f7d
  slug: polished-voice-7499
  revision: 0
  pushed_at: '2026-08-09T21:28:18+00:00'
  content_sha256: 2ef9c489375298675b89f7c85bebb57a3f403c9eef39f0e694b28a1d7bba09b1
---
# Where the link stalls actually live (2026-07-30, follow-up)

Parent `tiny-glitter-0842` closed with one open question: it attributed the ~200 ms telemetry
freezes to a blocking 100 ms I2C timeout in the bridge and said plainly that this was **a
hypothesis until `loop_max_ms` is read on hardware**. It has now been read. The hypothesis was
wrong, and the problem is one layer further out than anything I was looking at.

## What was measured

8 dashboard flights (`runs/pilot/flight_17854432xx–17854434xx`), plus bench RTT with motors off.
The bridge self-reports its worst `loop()` per 5 s window; that number now rides the ToF reply and
lands in the flight CSV as col 27, because the USB heartbeat is unreadable in the air.

## Result 1 — deploy fixes 1 + 2 CONFIRMED in flight (GREEN)

| | before (5 flights, old code) | after (8 flights) |
|---|---|---|
| phantom `h_err` steps > 0.15 m (obs moved, range did NOT) | **1** (0.449 m, 180 ms before a tumble) | **0** |

The ported sim gates are not merely present but *firing*: **11 over-range** readings (`tof_m`
reached 1.32–1.37 m, past the 1.3 m limit) and **97 over-tilt** readings were rejected across the
session. Every one of those would have entered the policy's observation as slant-range garbage
under the old code. These two fixes are done and validated on hardware.

## Result 2 — the I2C hypothesis is REFUTED (RED, my own)

`bridge_loop_max_ms` across all 8 flights: **1–13 ms**, with motors spinning, EMI, and real current
draw — exactly the conditions I predicted would trigger it. Meanwhile `obs_age_ms` reached p99
122–232 ms on 2.7–14.9% of ticks. **The bridge never stalled.**

The firmware changes (`setTimeout` 100→10 ms, poll 5→12 ms, UDP burst drain, blocking I2C last)
are not harmful and the per-section timers were worth their weight — but they did not fix this,
because this was never the bridge.

## Result 3 — the host is exonerated too

The CSV discriminates host-thread starvation from packet loss, because a blocked host would stop
ticking. During **every** stall tick, across all 8 flights:

| | dt p50 | dt p90 | dt max |
|---|---|---|---|
| stall ticks (obs_age > 100 ms) | 23 ms | 24–25 ms | 25 ms |
| clean ticks | 23 ms | — | — |

Identical. The host loop never missed a beat. Both endpoints are healthy; the packets are simply
not arriving.

## Result 4 — localized to the air, on the desk, motors off

`MSP_BRIDGE_TOF` is answered by the bridge and never reaches the FC, so its round trip **is** the
pure host↔bridge air path. Splitting the bench RTT (500 requests each):

| path | median | p90 | p99 | max |
|---|---|---|---|---|
| host→bridge→FC (ATT/IMU) | 25.71 ms | 62.21 | 197.36 | 650.56 |
| **host→bridge only (pure air)** | **11.05 ms** | **33.24** | **124.32** | **523.48** |

The FC path adds only ~14 ms of median on top of the air — ordinary UART + Betaflight MSP task
scheduling. **The air owns the tail.** And this was measured sitting on the desk with motors off,
reproducing the in-flight `obs_age` distribution almost exactly — so the stalls were never
flight-specific, never EMI, never current draw. The link is simply slow, always. Flying only
exposed it.

For scale: a 45 Hz control loop budgets **22 ms**. The air's **p90 alone is 33 ms**, and a
local-LAN UDP round trip should be 2–5 ms, not 11.

## Verdict / Honesty

**Deploy fixes GREEN. My stall hypothesis RED. Problem relocated to the WiFi hop, and it is now
the top blocker.** No tag for the node as a whole: confirming two fixes while refuting my own
diagnosis in the same measurement is genuinely mixed.

What this does NOT establish:

- **Which WiFi property is at fault.** Candidates, untested and ranked by cost: the host being on
  wireless at all (two air hops, and macOS runs periodic background scans that produce exactly
  this signature — irregular 100–500 ms stalls, load-independent); the mesh (BSSID
  `F4:B5:AA:91:44:09`, with repeaters — bench RSSI swung −43 to −59 dBm while stationary);
  2.4 GHz congestion; the ESP32 WiFi stack itself. I have already been wrong once here by
  reasoning ahead of measurement, so these stay explicitly hypotheses.
- **That the link explains the flight failures.** 5 of 8 flights ended inverted and none held a
  hover. The failure shape did change — the drone now overshoots to 1.32–1.37 m against a 1.0 m
  target and tumbles, rather than the previous pattern — which is *plausibly* downstream of a
  control loop eating 200 ms holes, but is not demonstrated.
- **Anything about the 25 Hz retrain.** Still untested; unrelated to this.

## Method note

The generalizable lesson: three rounds of bench diagnosis all came back clean (idle 4.5 /
ToF-polling 4.9 / full FC round-trip 5.1 ms) and each round I proposed a new suspect. What
actually resolved it was instrumenting the layers separately — bridge `loop_max`, host `dt`,
and an RTT split using a command that deliberately stops short of the FC — so each layer could
exonerate itself. Three of my named suspects (I2C timeout, WiFi modem sleep, `fc.readBytes`) were
refuted by measurement, not by argument.

## Lineage

Parent `tiny-glitter-0842` — characterized the ToF sensor, shipped the three deploy fixes, and
left the stall root cause explicitly unconfirmed. This node answers it: confirms that node's fixes
1 and 2 on hardware, refutes its fix-3 attribution, and relocates the problem to the WiFi hop.

Commits: `670efbd` (log `bridge_loop_max_ms` as CSV col 27), `a737dc2` (pin the dashboard CSV to
the analysis schema — the real flights fly that path), `078714a` (split the `latency` tail into
air vs FC path).

Next: host on ethernet and re-run the split; if the air stays slow, a dedicated AP off the mesh,
then ESP-NOW as the durable fix (SIM2REAL branch B). Target: air p99 under ~20 ms.