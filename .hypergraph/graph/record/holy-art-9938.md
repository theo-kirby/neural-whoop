---
node_id: f88f6be5-782e-57e4-a101-218014377101
slug: holy-art-9938
title: 'Studio Calibrate: the lag was two 20 ms polling terms (not the 2.4 ms link), and params{hz} had never retimed the fly loop at all — plus a ''frozen'' yaw that was a chart-scale collapse'
created_at: '2026-07-30T00:28:52.560792+00:00'
parents:
- polished-band-7171
- twilight-boat-1997
- icy-base-2242
summary: 'First real use of the Real tab''s Calibrate view after the rewire (parent icy-base-2242) produced two complaints, and decomposing them found two latent bugs. (1) LATENCY was polling architecture, not the link: Telemetry.poll sends its requests then drains NON-BLOCKING, so replies (~2.4 ms out) land after the drain and are eaten on the next tick (+20 ms at 50 Hz), and /ws/flight polled mgr.latest() behind sleep(0.02) (+0-20 ms) — while the measured link RTT contributes ~2.4 ms, i.e. the link everyone suspects was never the problem. Fixes: Calibrate requests 100 Hz on entry and restores the panel value on exit; websocket poll 20->5 ms (frames only send when seq advances, so no extra traffic). 100 Hz is bounded by the FC''s 115200-baud MSP UART at ~74 bytes/tick (ATTITUDE + RAW_IMU + MOTOR_TELEMETRY both ways; the ToF request is bridge-answered) = ~155 ticks/s ceiling, so ~64% utilisation. Noted: the link-age chart UNDERSTATES latency because t_att is stamped when the frame is read, not requested. (2) LATENT BUG - neither fix would have worked: _fly_loop hoisted period = 1/ctrl.params.hz above the loop, pinning it to the FIRST controller, so params{hz} AND the Bench panel''s hz field were silently dead for the loop rate while the controller still derived its ANALOG/RC cadence from p.hz. Any past flight with a non-default panel hz actually ran at the startup rate. The regression test asserts wall-clock per tick because both obvious assertions pass with the bug present (ctrl.params.hz always updates; a step-count check just waits longer); verified causally by re-introducing the hoist — 20 ticks took 1.05 s at the stale 20 Hz vs ~0.2 s fixed. 264 passed. (3) ''FROZEN'' YAW was a display defect, not a dropped signal: bench monitor shows heading tracking a hand rotation and wrapping (206->239->288->322->1->21->81->89), and 63 frames through the FlightManager carry a varying telemetry.yaw. Causes: unwrapped heading (negating MSP 0..359 gave only -359..0 with a full-turn jump; now wrapped to (-pi,pi], verified 359->+1, 1->-1, 206->+154; glyph unaffected modulo 2pi) and yaw setting the attitude chart''s symmetric auto-scale (a ~200 deg heading pushed attLim to ~200, collapsing the +-3 deg roll/pitch traces onto the centre line and pinning yaw to the chart edge — flat against the border reads as frozen); attLim is now roll/pitch only, yaw on its own +-180. HONESTY, no outcome tag: the latency gain is PREDICTED from the term sum, never measured end-to-end (and the link-age chart cannot measure it); the yaw complaint is NOT closed — the operator then saw it work only intermittently across power cycles, which neither fix explains, leading untested hypothesis being disturbed Betaflight gyro calibration at power-up (heading is pure gyro integration, no magnetometer, so it hits yaw specifically while accel-based roll/pitch survive), test = plug in and leave it still ~5 s, fallback = integrate r host-side; a third latency term (~10 ms, a bounded blocking read in poll()) is left untouched because it sits on the flight control path; MSP yaw is whole degrees so it steps coarsely even when healthy; and the bridge routes FC replies to the LAST host that sent a frame, so two clients steal each other''s replies — never run bench.py while the Studio server is up.'
origin:
  backend: flywheel
  node_id: f88f6be5-782e-57e4-a101-218014377101
  slug: holy-art-9938
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
---
# Calibrate-view latency, the dead hz knob, and the "frozen" yaw

**Trigger.** With the rewire working (parent **icy-base-2242**), the first real use of the Real tab's ⌘ Calibrate view surfaced two operator complaints: the attitude readout lagged visibly, and yaw appeared frozen.

## Setup
Bench Mac (CPU torch), `scripts/serve.py --device cpu --bridge <xiao>`, Air65 II powered, props off. Calibrate is telemetry-only — it never arms or commands — so all of this is measurable with no flight risk.

## Results

### 1. The latency was polling architecture, not the link
Decomposed from the code rather than guessed. Two ~20 ms terms dominated and the WiFi link contributed almost nothing:

| term | before | after |
|---|---|---|
| MSP poll staleness | ~20 ms | ~10 ms |
| WebSocket push | 0–20 ms | 0–5 ms |
| link RTT (measured) | ~2.4 ms | ~2.4 ms |
| browser render | 0–16 ms | 0–16 ms |

`Telemetry.poll` sends its requests then drains **non-blocking**, so replies (~2.4 ms out) arrive *after* the drain and are consumed on the next tick — one whole tick of staleness. Fixes: Calibrate asks for **100 Hz** on entry and hands the rate back to the panel value on exit; the `/ws/flight` poll drops 20 ms → 5 ms (frames are only sent when `seq` advances, so this adds no traffic).

**100 Hz is not arbitrary.** The ceiling is the FC's 115200-baud MSP UART, not WiFi: ~74 bytes/tick over the UART (ATTITUDE + RAW_IMU + MOTOR_TELEMETRY, both directions; the ToF request is bridge-answered and never reaches the FC) ⇒ 11520/74 ≈ **155 ticks/s** hard ceiling. 100 Hz sits at ~64% utilisation.

Also worth recording: **the link-age chart understates true latency.** `t_att` is stamped when the frame is *read*, not when it was requested, so a sample that is really a tick old reports ~0 ms. It is a link-health indicator, not an end-to-end latency measurement.

### 2. `params{hz}` had never retimed the loop (latent bug)
Neither fix above would have worked. `_fly_loop` hoisted `period = 1.0/ctrl.params.hz` **above** the loop, so it was pinned to whatever the *first* controller was built with. `_apply_commands` swaps in a new controller on `params` and `ctrl.params.hz` did change — but the sleep never looked at it again. So the Calibrate request **and the Bench panel's own `hz` field** were silently dead for the loop rate, while the controller believed it was running at the requested rate (it derives its ANALOG/RC poll cadence from `p.hz`). Any past flight flown with a non-default panel `hz` actually ran at the manager's startup rate.

The regression test asserts **wall-clock per tick**, because the two obvious assertions both pass with the bug present: `ctrl.params.hz` always updated, and a step-count check just makes the reader wait longer. Verified causally by re-introducing the hoist: 20 ticks took **1.05 s** at the stale 20 Hz vs **~0.2 s** fixed.

### 3. "Frozen" yaw was a chart-scale collapse, not a dropped signal
The FC was never at fault: `monitor` shows heading tracking a hand rotation and wrapping (206→239→288→322→1→21→81→89), and 63 frames captured through the whole `FlightManager` carry a varying `telemetry.yaw`. Two display defects:
- **Unwrapped heading**: negating MSP's 0..359 only ever gave −359…0° and jumped a full turn at the wrap. Now wrapped to (−π, π]; verified against the real headings (359°→+1°, 1°→−1°, 206°→+154°). Orientation unchanged modulo 2π, so the glyph is unaffected.
- **Yaw set the attitude chart's auto-scale**: a ~200° heading pushed `attLim` to ~200, collapsing the ±3° roll/pitch traces onto the centre line and pinning yaw to the chart edge — a trace flat against the border reads exactly like a frozen one. `attLim` is now roll/pitch only; yaw draws on its own fixed ±180.

## Verdict / honesty
No `outcome:` tag, deliberately — this is a mixed result with one item still open.

1. **The latency improvement is predicted, not measured.** ~45–60 → ~20–30 ms is the sum of the terms above; no end-to-end measurement was taken on hardware, and the link-age chart cannot provide one (see above). The `hz` bug fix, by contrast, is causally verified in test.
2. **The yaw complaint is NOT closed.** After both display fixes the operator reported yaw working only **intermittently** across power cycles — dead on several runs, perfect on one. Neither fix explains that. Leading untested hypothesis: Betaflight gyro calibration at power-up needs the craft held still, and heading here is pure gyro integration (no magnetometer), so a disturbed cal would hit yaw specifically while accelerometer-based roll/pitch keep working. Cheap test: plug in, leave it untouched ~5 s, check. Robust fallback if it recurs: integrate `r` host-side for the display.
3. **A third latency term remains untouched** — a bounded blocking read after the sends in `poll()` would remove the remaining ~10 ms, but it sits on the real flight control path and was deliberately left for a deliberate change.
4. MSP yaw is whole degrees while roll/pitch are 0.1°, so yaw steps coarsely even when perfectly healthy.
5. **Bridge constraint found while debugging:** the bridge ships FC replies to the *last* host that sent a frame (`main.cpp:166,178`), so two clients steal each other's replies — never run `bench.py` while the Studio server is up. This is a real hazard for any future A/B between the two.

## Lineage
Parents: **icy-base-2242** (the rewire that had to work before any of this was observable — same session), **polished-band-7171** (which named "decouple command rate from telemetry RTT / 100 Hz control" as the lever for the 2.5 Hz delay limit-cycle; this implements the display-side half of it and, via the `hz` bug, shows why the knob never took effect), **twilight-boat-1997** (the Studio UX line this view belongs to). Commits: `e3c2799` (latency + hz fix + regression test), `5440735` (yaw wrap + chart scale).