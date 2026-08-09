---
node_id: 3a8b6784-3956-58c3-8893-2e48f24c2946
slug: white-rice-3299
title: 'DEPLOY: hover_tof_air65_w128u15 shipped as the 1.0 m hover policy — weights + selftest 6.4e-08 + fake-bridge flight at 1.0 m verified, shove-recovery hero MP4 rendered; ★ studio-baseline moves here'
created_at: '2026-07-13T21:22:20.126618+00:00'
parents:
- calm-base-6054
- bitter-field-5265
- cold-tooth-8181
summary: 'Deploy decision + package for the hover_tof line (user choice at the second regroup, after 4 one-factor arms mapped a clean-trim↔noise-robustness frontier with no gate-dominant point): SHIP hover_tof_air65_w128u15 — cleanest hover of the line (no-DR tilt 0.22°, z err 0.047 m, survival 100%), M1-live 100/100/95.4/64.9% @0.5–1.2×, m2sensor 36.5%; ≥1.2×-tail risk covered by bridge IMU oversampling (effective noise <1.0×) + tof_lost abort + radio kill. Deploy target now 1.0 m (FlightParams/--target-height default, commit a8d37dc). Package verified end-to-end: policy_weights.json 23.3k params, selftest parity 6.44e-08 + corrective signs OK, ONNX max diff 3.6e-07, fake-bridge full WAITING→…→RELEASED flight at 1.0 m with h_err = 1.0 − tof·cosr·cosp byte-exact in CSV cols 25/26. Hero MP4s via nw-viz: shove twin (setpoint pinned 1.0 m, wind 1.0, impulse_prob 0.03, live 1.0× noise, latency 0) shows kick→tumble→recover→re-lock; clean pack alongside. Bench handoff (hardware-gated, user flies): pilot.py --udp <bridge-ip> --weights runs/hover_tof_air65_w128u15/policy_weights.json fly --takeoff --target-height 1.0 --seconds 15 --ack-props-on; the first real ToF flight calibrates the placeholder h-noise DR from cols 25/26. ★ studio-baseline moves here (from d50var_s8/broken-wildflower-8398). Commits a8d37dc/35173ab; docs TASK_CATALOG + SIM2REAL updated.'
origin:
  backend: flywheel
  node_id: 3a8b6784-3956-58c3-8893-2e48f24c2946
  slug: white-rice-3299
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 3ddde17f-64e5-582c-98ed-f3a86f82961d
  slug: muddy-poetry-0718
  revision: 0
  pushed_at: '2026-08-09T21:28:18+00:00'
  content_sha256: bc2c1a81df2bf462eadd20b56828a4884e2d8773be939bff7d36af2a6531a03b
---
# Deploy: w128u15 at 1.0 m — the compromise arm ships, with its risks stated

**Decision.** After the 4-arm leveling ladder ended with a frontier and no all-gates arm, the user chose `hover_tof_air65_w128u15` (calm-base-6054) as the deploy policy. Rationale: cleanest hover of the entire hover line (no-DR tilt 0.22°, z err 0.047 m, 100% survival), perfect survival at ≤0.8× amplitude and 95.4% at 1.0× — and the real bench's effective noise sits *below* 1.0× because the bridge oversamples the IMU between 50 Hz tick reads. The known weakness (m2sensor 36.5%, 1.2× 64.9%) is a stacked bias+rate-gain+latency+high-amp regime; on a 15 s first flight at 1 m it is bounded by the `tof_lost` abort (>1 s sensor silence), the radio's instant kill, and the flight-clock auto-land.

**Package (all verified this session, commits a8d37dc…35173ab).**
- Deploy default **1.0 m**: `FlightParams.target_height_m` and `pilot.py --target-height` 0.6→1.0 (Studio Bench inherits). Inside the trained 0.5–1.1 m band; VL53L1X short-mode-valid (1.3 m slant saturation).
- Exports: `policy.pt` / `policy.onnx` (max diff 3.6e-07) / `policy_weights.json` (23,300 params — ~1 ms/step in the pure-Python 50 Hz pilot; attached).
- `NW_FLIGHT_FAKE=1 pilot.py selftest`: parity vs ref outputs **6.44e-08**; level-still ≈ hover_us, nose-down→nose-up + tilt-right→roll-left corrective signs OK.
- Fake-bridge system flight (`fly --takeoff --target-height 1.0 --seconds 15`): full WAITING→countdown→liftoff-seek→policy→ramp-down→RELEASED; 26-col log with `tof_m`/`h_err` (cols 25/26) and `h_err = 1.0 − tof·cosr·cosp` exact (0.030→0.9700, 0.321→0.6790); 1044 frames, 0 stale ticks (CSV attached).
- Hero MP4s (nw-viz, 1499 frames each): **shove video** from the `hover_tof_air65_shove.yaml` eval twin — setpoint pinned exactly 1.0 m, live 1.0× sensor noise, wind 1.0 m/s², `impulse_prob 0.03` (≈1.5 kicks/s), latency 0 for visual honesty — kick→tumble→recover→re-lock at 1 m (attached, 1.4 MB); clean-pack MP4 alongside (attached).

**Bench handoff (hardware-gated — the user flies):**
```
python3 scripts/pilot.py --udp <bridge-ip> --weights runs/hover_tof_air65_w128u15/policy_weights.json \
    fly --takeoff --target-height 1.0 --seconds 15 --ack-props-on
```
Setup refuses without live ToF; `tof_lost` abort armed; radio owns enable + instant kill. The first real ToF flight doubles as the **h-noise DR calibration** — CSV cols 25/26 replace the datasheet-placeholder sd 0.02 m / bias ±0.03 m, which is also the highest-value input to any future arm on this frontier.

**Honesty.** (1) This ships with two agreed gates unmet (M1-live 1.0× 95.4% vs ≥98; m2sensor 36.5% vs ≥42) — a user decision with mitigations, not a gate pass; the ★ pointer move records the hand-off, not a GREEN. (2) The oversampling argument (effective noise <1.0×) is plausible but unmeasured — exactly what the first flight's CSV settles. (3) Altitude risk is the best-covered axis: zero floor/ceiling exits in every probe of every arm in the line.

**Lineage.** Parents: calm-base-6054 (the shipped arm), bitter-field-5265 + cold-tooth-8181 (the frontier alternatives whose outcomes framed the choice). ★ studio-baseline moves here from broken-wildflower-8398 (d50var_s8) — the first baseline hand-off with a closed altitude loop. Next: the real 1 m ToF flight (bench, user), then h-noise recalibration → whichever frontier attack the measured noise justifies.