---
node_id: fe75a7cb-0cf7-5b5f-a5d4-fa0870aeb621
slug: forest-timber-8727
title: The ESP-NOW link is built and flying, its own bench gates are unmet, and its stated premise was refuted
created_at: '2026-08-09T18:42:33+00:00'
parents:
- modest-raven-7153
summary: Peer-to-peer ESP-NOW replaced the WiFi/UDP bridge end to end and confirmed its hypothesis that the tail was association overhead rather than 2.4 GHz congestion. Both pre-registered bench gates still miss, the in-flight tail has since regressed to the WiFi baseline, and docs/ESPNOW.md still describes the link as awaiting bring-up.
---
Status: open

## Current

Built end to end: an `espnow_dongle` firmware (USB CDC to ESP-NOW with MSP
re-framing, oversize frames dropped and counted at the 250 byte cap, a lock-free SPSC
ring), a four-call transport seam behind `-DNW_LINK_ESPNOW` in the bridge, and host
wiring through `pilot.py --serial` and the Studio. WiFi stays the default build so
rollback is one reflash [rec: shiny-queen-9632].

**It confirmed its own hypothesis.** On the bench the stall signature is gone —
0 of 500 samples over 100 ms, full-trip p99 197.36 to 38.53 ms, max 650.56 to
62.94 ms, air p99 124.32 to 26.44 ms — and since this is the same band in the same
room, a 4.7-5.1x p99 improvement from removing association alone confirms that the
tail was AP and association overhead rather than 2.4 GHz congestion
[rec: black-firefly-9000].

**Both bench gates still miss, and were reported as failures rather than rounded
down**: air p50 6.22 ms against a target under 5, air p99 26.44 ms against a target
under 20. About 4 ms of the residual p50 is the drone's own blocking I2C ToF poll
[rec: black-firefly-9000].

**And in the air it has since regressed.** The most recent flight session over
ESP-NOW measured in-flight p99 123-226 ms with up to 9.3% of frames over 100 ms — no
better than the old WiFi baseline of 122-232 ms [rec: broken-fire-4858]. An earlier
ESP-NOW session had been healthy (p99 48-69 ms, 0.00% of ticks over 100 ms), so this
is a regression, not a steady state.

## Negative knowledge

- [scope: the premise that the link explained the flight failures | confidence: high | evidence: broken-fire-4858] Refuted, and recorded as such in docs/SIM2REAL.md (2026-07-31). Four ESP-NOW flights with the link finally healthy flew exactly the same failure as the eight WiFi flights before them — peak height 1.36-1.37 m against a 1.0 m target, then motors off and a drop. The link and the control fault are two separate faults and are now cleanly separated.
- [scope: docs/ESPNOW.md as a status document | confidence: high | evidence: shiny-queen-9632, black-firefly-9000, broken-fire-4858] The doc still reads 'implemented, awaiting hardware bring-up' and still quotes the WiFi baseline numbers as 'current' in its acceptance-gate table. The bring-up happened, the link has flown, and the gate table was never updated. Its line 3 is also a truncated sentence.
- [scope: broadcast pairing and application-level retry | confidence: high | evidence: shiny-queen-9632] Both were considered and rejected with reasons rather than deferred silently: fixed compiled-in peer MACs because two boards on a bench do not need discovery and fixed MACs are immune to a stray packet re-pointing the telemetry stream, and fire-and-forget because for a 50 Hz control link stale data is worse than missing data.

## Provenance

- winter-sun-6292 — the localisation of the tail to the air hop that motivated the rebuild
- shiny-queen-9632 — the link built end to end, and the design calls behind it
- black-firefly-9000 — the hardware measurement, the confirmed hypothesis, and the two missed gates
- broken-fire-4858 — the in-flight regression and the refuted premise
