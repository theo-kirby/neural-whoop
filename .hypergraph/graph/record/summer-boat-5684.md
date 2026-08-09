---
node_id: 7415396c-1eed-5b98-8f8f-e91e0c236d59
slug: summer-boat-5684
title: 'Control: onboard-compute path for the tiny whoop (chip on the Air65 II)'
created_at: '2026-07-02T10:05:03.464255+00:00'
parents:
- long-fog-2207
- blue-unit-1398
summary: 'CLOSED (objective_met): onboard compute is trivially feasible — real policy = 79 KB flash / 1 KB RAM / ~0.55 ms on the Air65 II''s own G473 (parity 4.8e-7); docs/ONBOARD_COMPUTE.md ranks paths, recommends gram-class MSP companion first (hybrid-obs architecture), BOM ~$40–55 awaiting approval. ~0.6 h used, 0 credits. Next: O-3 hybrid-obs retrain (no hardware needed).'
origin:
  backend: flywheel
  node_id: 7415396c-1eed-5b98-8f8f-e91e0c236d59
  slug: summer-boat-5684
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Run contract

- Objective: Map and de-risk a concrete path to ONBOARD policy execution on the Air65 II: (1) empirical feasibility measurement (C export of the real gate_race_air65 policy, parity, cross-compiled flash/RAM/cycle budgets); (2) decision document docs/ONBOARD_COMPUTE.md ranking paths A (existing STM32G473 FC in Betaflight) / B (gram-class companion MCU over MSP) / C (camera+NN deck), with BOM for user approval.
- Decision criterion: (a) parity < 1e-5 max-abs on the real checkpoint; (b) flash/RAM/latency for ≥3 chips from a real cross-compiled binary; (c) doc ranks paths with explicit recommendation + BOM, nothing purchased autonomously.
- Start nodes: blue-unit-1398, long-fog-2207, bitter-fire-0679.
- Budget ceiling: 3
- Budget unit: hours of local wall-clock on this workstation
- Compute approval cap: 0 Flywheel credits — local-only per locked decision #3; no hardware purchased.
- Lookahead depth: 1
- Frontier width: 1
- Terminal condition: measurement + analysis nodes committed with artifacts, or budget reached.
- Stop reason: **objective_met** (2026-07-02; ~0.6 h of 3 h used; 0 credits; all three criteria met).

## Outcome

- Measurement node sparkling-shadow-2507 (O-0, GREEN): `scripts/export_c.py` exports the real policy to dependency-free C — **parity 4.8e-7**, **79.3 KB flash / 1.0 KB RAM on Cortex-M4** (zig cross-compile, M4/M7/M33 all measured), host 8.4 µs, projected **~0.55 ms (≈0.5% CPU @ 100 Hz) on the Air65 II's own STM32G473**. Refutes SIM2REAL.md's "RAM-tight" deferral rationale; real constraints = flash-next-to-Betaflight (O-2) and obs sourcing. Artifacts: results + generated C.
- Analysis node little-term-0124: hybrid-obs architecture (fresh local state obs + ~30 Hz uplinked target channel = strictly smaller sim2real gap than full offboard); paths ranked — **B (gram-class MSP companion, +1–3 g, ~$15–25) recommended first** (no Betaflight fork; also retires the SIM2REAL flow-deck integration risk), A (G473 in Betaflight, 0 g) as the racing end-state pending O-2 flash measurement, C (camera deck) deferred. Staged plan O-0..O-4; BOM ~$40–55 awaiting approval. Artifact: docs/ONBOARD_COMPUTE.md @ f618b12 (committed + pushed).

## Staged frontier (next passes)
1. **O-3 hybrid-obs retrain (no hardware, ~5 min GPU):** split latency DR — fresh state obs, 30 Hz stale target channel — quantify how much of blue-unit-1398's latency tax the onboard architecture buys back. The highest-value next empirical node in cluster:deploy-hw.
2. **O-2 Betaflight Air65 II target build** (local, no sudo path to verify) → flash headroom go/no-go for Path A.
3. O-1 companion bench rig — blocked on user approving the BOM.
4. Int8 quantized export variant of export_c.py (only needed if O-2 shows <80 KB headroom).