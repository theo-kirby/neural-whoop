---
node_id: c2f1b33c-d62e-5b07-9b51-9e30632e34c9
slug: black-firefly-9000
title: 'ESP-NOW on hardware: the 100-650 ms stall signature is GONE (0/500 over 100 ms, p99 197→39 ms full-trip) but both bench gates MISS. The first numbers were worse than WiFi — root cause was my own USB CDC buffering, not RF'
created_at: '2026-07-30T22:24:00.900195+00:00'
parents:
- shiny-queen-9632
summary: 'ESP-NOW measured on hardware against the WiFi baseline, identical bench.py method, n=500, motors off. The stall signature that broke the flights is GONE: full-trip p99 197.36→38.53 ms, max 650.56→62.94 ms, air p99 124.32→26.44 ms, and 0/500 samples exceed 100 ms (was 2.7-14.9% of ticks over 100 ms in flight). BOTH bench gates still MISS: air p50 6.22 (wanted <5), air p99 26.44 (wanted <20) - reported as failures, not rounded down; ~4 ms of the residual p50 is the drone''s own blocking I2C ToF poll. The hypothesis that the tail was AP/association overhead rather than 2.4 GHz congestion is CONFIRMED: same band, same room, 4.7-5.1x better p99 from removing association alone, so the plan''s named failure mode did not materialise. Critically, the FIRST numbers were WORSE than WiFi (p50 12.66, p90 526, ~20% missing deadline) and the cause was MY bug, not RF: the dongle held replies in its USB CDC FIFO and delivered them in batches. Byte accounting proved ZERO packet loss (5600/5600 arrived) - they were merely late. Serial.flush() per write took delivery 310/400 -> 400/400. Three hypotheses (UART flood, STA auto-reconnect, RF congestion) were refuted by measurement first. Finding it required giving the deliberately-silent dongle an in-band counter id (MSP 193), since Serial is its data path; loopback hid the bug entirely because that build never starts WiFi. Also fixed a latent silent-data-loss bug: Serial.write()''s short-count return was ignored. NO outcome tag - gates missed, blocker resolved, hypothesis confirmed, own implementation at fault. Flight gates (obs_age p99 <40 ms, ticks>100ms <0.5%) remain UNMEASURED; full-trip p99 38.53 sits on the 40 ms line with no margin. Commits 06d080b, 7e9928b.'
origin:
  backend: flywheel
  node_id: c2f1b33c-d62e-5b07-9b51-9e30632e34c9
  slug: black-firefly-9000
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: ebce3400-2a71-5f9c-8208-d3eb1598195d
  slug: still-tree-1317
  revision: 0
  pushed_at: '2026-08-09T21:28:18+00:00'
  content_sha256: a3dc5680460a4bdae57c3ee297a6dd3181218299adad40f03116c92c8f9c334a
---
# ESP-NOW bench result (2026-07-31)

## Hypothesis

Parent `shiny-queen-9632` built the link to test one specific thing: **that the WiFi tail was
AP/association overhead — beacons/DTIM, DHCP, mesh roaming, macOS background scans — rather than
2.4 GHz congestion.** ESP-NOW removes all of the former and keeps the band, so it is a clean
discriminator. The plan named congestion as the way this underdelivers.

## Setup

Both XIAOs flashed (`xiao_bridge_espnow` + `espnow_dongle`), MACs from `mac_probe`, **channel 11**
chosen from a bench scan (2.4 GHz neighbours at ch 1×2, 3×2, 4×2, 6×2, 13×2, 11×1 — 3 overlapping
APs vs 6 on ch 1/6). Desk, motors off, props off, drone bridge on the flight battery via the FC
BEC. `scripts/bench.py latency --n 500`, the identical call that produced the WiFi baseline.

## Result 1 — the tail is transformed (the thing that broke the flights)

| | WiFi | ESP-NOW | |
|---|---|---|---|
| air p50 | 11.05 | **6.22** | 1.8× |
| air p90 | 33.24 | **13.62** | 2.4× |
| air p99 | 124.32 | **26.44** | 4.7× |
| air max | 523.48 | **36.35** | 14.4× |
| full-trip p50 | 25.71 | **15.17** | 1.7× |
| full-trip p90 | 62.21 | **24.77** | 2.5× |
| full-trip p99 | 197.36 | **38.53** | 5.1× |
| full-trip max | 650.56 | **62.94** | 10.3× |

**0 of 500 samples exceed 100 ms.** The original failure was a 45 Hz loop (22 ms budget) hitting
100–650 ms holes on 2.7–14.9% of ticks; the worst round trip now measured is 63 ms. The FC leg
costs ~9 ms of the median — ordinary UART + Betaflight scheduling, the floor rather than the link.

## Result 2 — both bench gates MISS

| gate | target | measured | |
|---|---|---|---|
| air p50 | < 5 ms | 6.22 | FAIL |
| air p99 | < 20 ms | 26.44 | FAIL |

Stated as failures rather than rounded down. Roughly 4 ms of the residual p50 is the drone's own
blocking I2C ToF poll (`loop_max` 3.8 ms, all of it `poll_tof`) — a packet arriving mid-transaction
waits for it. That is a real knob but it trades against ToF sample rate, already tuned to 25 Hz in
`tiny-glitter-0842`, so it was left alone rather than quietly regressing the height channel.

## Result 3 — the hypothesis is CONFIRMED, and congestion is not the story

Same band, same room, same evening: peer-to-peer cut p99 4.7–5.1×. If neighbours saturating
2.4 GHz owned the tail, removing association would not have done that. The plan's named failure
mode did not materialise.

## Result 4 — the first numbers were WORSE than WiFi, and it was my bug (RED, my own)

First air measurement: p50 12.66, p90 526, ~20% of round trips missing their deadline. Three
explanations died to measurement before the real one:

- *bridge relaying floating-UART garbage with the FC dark* — refuted: 0 unsolicited bytes in 3 s.
- *STA auto-reconnecting to a stored AP and hopping channels* — refuted: neither board on the LAN.
- *RF congestion* — refuted by what follows.

Layer isolation settled it: the loopback build (USB CDC + dongle loop, radio bypassed) measured
**p50 0.12 ms, 0/300 slow**; the drone's self-reported `loop_max` was **3.8 ms**. Both endpoints
free. But the dongle was **unobservable by design** — `Serial` IS its data path, so `-DDONGLE_DEBUG`
needs a second UART on wires the bench does not have. Giving it a dongle-answered MSP id (193, same
contract as the bridge's ToF id: answered locally, never forwarded) ended the guessing in one run:

```
air_tx 400   rx_pkts 400   usb_bytes 5600   ring_drop 0   send_fail 0   usb_short 0
```

Every request out, every reply back over the air, every byte handed to CDC — while the host saw 310.
Byte accounting closed it: **5600 of 5600 bytes arrived. Zero packet loss, ever.** Replies were
sitting in the dongle's USB CDC FIFO and being delivered in batches once enough piled in behind
them, so ~22% missed a 250 ms deadline. `Serial.flush()` after each write took delivery to 400/400.

A second, latent bug found on the way: `Serial.write()`'s short-count return was ignored, advancing
`ring_tail` past bytes CDC had not accepted and counting them as sent. Measured `usb_short 0`, so it
was not the cause — but it is silent data loss under back-pressure and is now fixed and counted.

**Loopback hid the real bug completely, because that build never brings WiFi up and so never
contends for the CDC FIFO.** The bring-up step designed to de-risk the transport was the one blind
to its defect.

## Verdict / Honesty

**No `outcome:` tag.** Gates missed, blocker resolved, hypothesis confirmed, and my own first
implementation was the thing making it look bad — a single verdict would misrepresent that.

What this does **not** establish:

- **Anything in flight.** `obs_age_ms` p99 < 40 ms and ticks-over-100 ms < 0.5% are the gates that
  actually matter and both are **unmeasured**. Full-trip p99 is 38.53 ms, i.e. sitting right on the
  40 ms line with no margin.
- **That the link explains the flight failures.** 5 of 8 flights ended inverted, overshooting to
  1.32–1.37 m against a 1.0 m target. Still plausibly downstream of 200 ms holes, still not
  demonstrated. Fixing the link may simply expose a control problem.
- **That ch 11 is optimal**, or how this behaves at flying distance rather than across a desk.
- The battery read 3.67 V at the end of the window — too flat to fly, so no flight was attempted
  rather than burning a window on an uninterpretable result.

## Method note

The generalisable lesson repeats the parent's: every layer must be able to exonerate itself, and a
component with no instrumentation cannot. The dongle was deliberately silent for good reasons and
that decision cost roughly an hour; the fix was not a jumper wire but an in-band counter id, which
is now permanent. Also worth recording: the first measurement method was itself wrong — a single
MSP id means a *late* reply satisfies the *next* request and reports a fake fast RTT, exactly what
`bench.py::_rtt_samples` documents and avoids by cycling two ids. Flushing the input buffer per
request was needed before the loss numbers meant anything.

## Lineage

Parent `shiny-queen-9632` — built the link and set up this measurement. Grandparent
`winter-sun-6292` — localized the tail to the air hop and supplied the WiFi baseline every number
here is compared against.

Commits `06d080b` (implementation), `7e9928b` (the CDC fixes + the dongle stats id).

Next: charged pack → Studio Real tab on the dongle → `flight_report.py` → compare `obs_age_ms` p99
against the 122–232 ms baseline. That is the gate that decides whether this ships.