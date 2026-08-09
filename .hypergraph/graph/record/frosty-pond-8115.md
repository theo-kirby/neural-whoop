---
node_id: b98b704d-7fce-568c-a3d6-f246fb487aa7
slug: frosty-pond-8115
title: 'Method: Stage-0 MSP bench toolkit — pure-stdlib MSP v1 codec + safety-gated CLI (info/monitor/latency/rc-test/motor-test)'
created_at: '2026-07-04T09:05:38.453888+00:00'
parents:
- bitter-fire-0679
- long-queen-3431
summary: 'Built the Stage-0 bench instrument (commit 0ea71b2): src/neural_whoop/bench/msp.py — pure-stdlib MSP v1 codec (encode/incremental-parse/decoders for ATTITUDE, RAW_IMU, ANALOG, RC, MOTOR, SET_RAW_RC, SET_MOTOR; 8 unit tests, no hardware needed; repo suite 117→125 green) + lazy-pyserial MspClient; scripts/bench.py CLI with info / monitor(csv) / latency(round-trip stats) / rc-test(MSP_SET_RAW_RC loopback — the offboard-control-seam smoke test) / motor-test. Safety by construction: writing subcommands require --ack-props-off, motor values hard-capped at 1200, arming is never touched (stays with the human on the Pocket). Channel-order caveat (BF rcData ROLL,PITCH,YAW,THROTTLE vs AETR wire order) documented; verifying it IS what rc-test is for. MSP v2 (flow-deck sensor messages) documented follow-up. Unblocks the user''s first hands-on bench session — the drone + Pocket + XIAO are in hand; the ELRS TX module is backordered, which this path doesn''t need.'
origin:
  backend: flywheel
  node_id: b98b704d-7fce-568c-a3d6-f246fb487aa7
  slug: frosty-pond-8115
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 7eecb948-0304-54b7-9fef-13e4ba7c2924
  slug: delicate-hill-3754
  revision: 0
  pushed_at: '2026-08-09T21:26:51+00:00'
  content_sha256: c7615228f02d17e38d25cc7f579f8aada23d16413a325a3ec5438a95559b3c1f
---
# Method: Stage-0 MSP bench toolkit

**Why.** Hardware arrived (Air65 II + Pocket + XIAO; ELRS TX module backordered — doesn't matter, see the branch map: branch B needs no module). Stage 0 of docs/SIM2REAL.md is a bench bring-up over USB; this is its instrument. Commit `0ea71b2` (theo-kirby/neural-whoop).

**What.**
- `src/neural_whoop/bench/msp.py` — MSP v1 codec, pure stdlib: `encode_msp_v1`, incremental `MspParser` (resyncs after garbage, drops bad-checksum frames), decoders for ATTITUDE (0.1-deg), RAW_IMU (raw ints on purpose — scale factors are board-lore, calibrated at the bench, not assumed), ANALOG (legacy u8 + modern u16 voltage), RC/MOTOR (n×u16), `pack_rc_channels` (clamps to Betaflight's 885–2115 valid band). `MspClient` wraps pyserial (lazy import — the `bench` extra; codec imports core-clean).
- `scripts/bench.py` — subcommands: `info` (FC identity/battery), `monitor` (attitude/IMU/RC/vbat at --hz, optional CSV), `latency` (MSP round-trip stats = the USB floor of the control budget), `rc-test` (stream neutral `MSP_SET_RAW_RC` + echo `MSP_RC` back — the loopback proof that the msp_override seam works and channel order is right), `motor-test` (one motor, props off, capped).
- Tests: 8 codec tests incl. byte-at-a-time chunking and resync-after-corruption; suite 125 green.

**Safety by construction.** Writing subcommands refuse to run without `--ack-props-off`; motor values hard-capped at 1200 (no override flag exists); no code path raises an arm channel — arming stays with the human on the Pocket. Documented BF gotchas in-code: rcData channel order (ROLL,PITCH,YAW,THROTTLE — MultiWii legacy, not AETR), the 300 ms MSP-RC freshness window, `msp_override_channels_mask`/`msp_override_failsafe` config prerequisites.

**Next (empirical, needs the drone on USB).** info → monitor sanity → latency baseline → rc-test loopback (checks whether BetaFPV's shipped 2026.6 build compiles MSP_OVERRIDE in — open question) → motor-test → rate-curve/step-response capture (feeds K_angvel + thrust numbers back into dynamics/whoop.py). MSP v2 support is the documented follow-up for the flow-deck sensor messages.

**Lineage.** Implements the Stage-0 tooling called for by the sim2real plan (`bitter-fire-0679`) in the hardware-in-hand context of the branch map (`long-queen-3431`). Sibling of the same-day `hover_air65_bridge` first-flight training sweep (node to follow with its visual pack).