---
node_id: 1ee227df-bfe7-515f-bf57-5d4079272406
slug: snowy-heart-2157
title: 'Bench Start interlock fix: the params rebuild raced request_start — software Start silently rejected on every click (fixed + regression test)'
created_at: '2026-07-10T17:07:22.552181+00:00'
parents:
- rapid-meadow-0957
summary: 'Field bug from the parent rapid-meadow-0957''s first real bench use: with the drone ARMED + override engaged and the Start button enabled, clicking Start did nothing — every time. Root cause: bench.js fires {params} then {start} back-to-back on one click; the params handler rebuilds a fresh WAITING FlightController, whose armed_seen/override_on are False until its first step() polls RC, so request_start — evaluated on that fresh controller in the SAME command drain — rejected the start and the drone never left WAITING. Fix (commit 65ef009): carry the previous live controller''s radio-observed armed_seen/override_on onto the rebuilt controller; the next step() re-verifies from RC and the radio still owns enable + instant kill, so the interlock is unchanged. Verified causally on the fake bridge: pre-fix params+start stays `waiting`, post-fix reaches `countdown`; a new regression test sends the exact bench.js message order (fails pre-fix, passes post-fix); full flight suite 11/11 green. Same session also rewired the XIAO bridge FC UART to D10/GPIO9 (FC R1) + D9/GPIO8 (FC T1) after the D8 lane, commit b27908a, MSP info round-trips confirmed. Cleared the way for the first dashboard-driven flight session (child node).'
origin:
  backend: flywheel
  node_id: 1ee227df-bfe7-515f-bf57-5d4079272406
  slug: snowy-heart-2157
  revision: 1
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 6deb9dbc-6139-521d-81ea-aed4293484c9
  slug: solitary-voice-1790
  revision: 0
  pushed_at: '2026-08-09T21:27:48+00:00'
  content_sha256: 8fb4250c32b03a21c3f69107fb19b8429c1a3c77846e7cd63d753e932da46f50
---
# Bench Start interlock fix — params rebuild raced request_start

**Symptom (first real-hardware use of the Bench tab, 2026-07-10).** Drone ARMED + MSP-override engaged on the Pocket radio, telemetry green, Start button *enabled* — but clicking Start did nothing, reproducibly. No error surfaced; the phase chip stayed `waiting`.

## Root cause
`bench.js` sends **two** websocket messages per Start click: `{type:"params", ...}` immediately followed by `{type:"start"}`. Both land in the FlightManager's command queue before the next 50 Hz tick, so `_apply_commands` drains them together:

1. `params` → rebuilds a **fresh WAITING** `FlightController` (that's how param changes take effect).
2. `start` → `request_start()` on that fresh controller.

But `request_start` is gated on the controller's own `armed_seen and override_on` — flags that are only set inside `step()` from polled RC. The just-rebuilt controller **hasn't stepped yet**, so both are `False` → every Start is rejected. The next frame re-observes armed+override and re-enables the button, which is why the UI looked healthy while silently eating every click.

## Fix (`studio/flight.py`, commit `65ef009`)
When `params` rebuilds the controller, carry the **previous live controller's** radio-observed `armed_seen`/`override_on` onto the new one. The next `step()` re-reads RC and re-verifies; software still never writes arm/aux; the radio still owns enable + instant kill — the safety interlock is unchanged, only the stale-snapshot race is closed.

## Verification
- **Causal, on the fake bridge:** the exact `params`+`start` sequence pre-fix → stays `waiting`; post-fix → reaches `countdown`. `start`-only worked in both (which is why the existing tests missed it).
- **Regression test** `test_params_then_start_same_batch_flies` sends the bench.js message order verbatim — fails on the pre-fix tree, passes post-fix.
- **Full flight suite** (`test_flight_ws.py` + `test_flight_controller.py`): 11/11 green.
- **Field:** the child flight-session node — 7 browser-driven real flights, Start worked every time.

## Same-session bench work
Rewired the XIAO bridge FC UART to **D10/GPIO9 → FC R1** and **D9/GPIO8 → FC T1** (commit `b27908a`, config + README); `bench.py --udp info` round-trips over WiFi on the new pins. (History: D7/GPIO44 input is ESD-dead, D8/GPIO7 was the interim RX.)

## Lineage
Parent: **rapid-meadow-0957** (the unified Bench dashboard) — this fixes its Start path, found on first real-hardware contact. Fix commit `65ef009`; flown at `b27908a`. The regression-test discipline mirrors the fake-bridge headless harness the parent shipped.