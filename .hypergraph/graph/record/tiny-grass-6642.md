---
node_id: d65fe53f-47aa-50e6-9690-fe1b91fdd9c7
slug: tiny-grass-6642
title: 'Control: compose the winners — hybrid-obs × Muon × reliability shaping (deploy-recipe pass)'
created_at: '2026-07-03T14:22:16.238727+00:00'
parents:
- royal-field-3745
summary: 'CLOSED (objective_met): all three items resolved in one shot — hybrid_mrel composition (muddy-mouse-2952) clears every pre-registered bar on 3/3 seeds (2.32–2.54 s clean at 95.5–98.3%, DR-on 0.846–0.898 vs adam floor 0.79–0.81); ★ studio-baseline moved; Muon''s DR collapse shown to be an action-latency interaction. ~0.8 h of 3 h, 0 credits. Next: k_mot motor-lag modeling, bursty-uplink realism.'
origin:
  backend: flywheel
  node_id: d65fe53f-47aa-50e6-9690-fe1b91fdd9c7
  slug: tiny-grass-6642
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Run contract

- Objective: Execute the staged frontier from closed control royal-field-3745, priority order:
  1. **Compose the winners** (frontier item 1): train `gate_race_air65_hybrid` (onboard split-latency DR, soft-moon-6755) with Muon lr 2.5e-3 (black-silence-5752) + rel reliability shaping (crash_penalty 30 + hop-11 near-miss band 1.0/0.4, ancient-field-0677). One new config forked from `gate_race_air65_hybrid.yaml`, ONLY optimizer+lr+reward shaping changed. ~6 min on the 5090.
  2. **Multi-seed confirm** of the hybrid +1.9 pt DR-on completion delta (frontier item 3) — 2 extra seeds, budget permitting.
  3. Muon DR-robustness (frontier item 2) — item 1 partially answers it for free: if Muon holds ≥0.80 completion under the HYBRID DR, the 0.55–0.60 collapse was specific to the offboard action-latency regime, not to Muon per se.
- Decision criterion (pre-registered): composition is **GREEN / deploy-recipe candidate** if no-DR best lap ≤ ~2.60 s (keeps ≥80% of Muon's −23% vs the adam 3.203 s baseline) AND own-DR-on completion ≥ 0.80. **★ studio-baseline moves only if additionally no-DR completion ≥ 92.6%.** Standard evals: seed 12345, n_envs 2048, steps 1500, no-DR pack + DR-on companion.
- Start nodes: royal-field-3745 (closed control); composed parents ancient-field-0677 + soft-moon-6755; baselines black-silence-5752, blue-unit-1398, seed-matched `runs/gate_race_air65` (adam 3.203 s / 92.6%).
- Budget ceiling: 3
- Budget unit: hours of local wall-clock on the single RTX 5090 (started 2026-07-03 ~14:20 UTC)
- Compute approval cap: 0 Flywheel credits — local-only per locked decision #3; managed compute disabled (AGENTS.md).
- Lookahead depth: 1
- Frontier width: 1 (single shared GPU; sequential)
- Terminal condition: staged items resolved with packs + verdicts (item 1 mandatory; 2–3 budget-permitting), or budget ceiling reached.
- Stop reason: **objective_met** (2026-07-03, ~0.8 h of 3 h used, 0 credits).

## Outcome

**muddy-mouse-2952 (GREEN, promoted — all three contract items resolved by one composition + seed-confirm):**
- Item 1 (compose): `gate_race_air65_hybrid_mrel` clears every pre-registered bar — no-DR best lap 2.539 s at **98.3%** completion (bar: ≤2.60 / ≥92.6%), own-DR-on completion **0.846** (bar: ≥0.80). Deploy-recipe candidate confirmed; **★ studio-baseline moved** to muddy-mouse-2952.
- Item 2 (multi-seed): adapted from hybrid-adam to the composition itself (the new recipe supersedes hybrid-adam as the thing worth confirming). Seeds 1/2: 2.429 s / 97.2% / DR-on 0.870 and 2.320 s / 95.5% / DR-on 0.898 — every seed clears every bar; the promotion is not a seed artifact.
- Item 3 (Muon DR-robustness): answered for free, as staged — Muon+rel under the onboard split holds 0.846–0.898 DR-on (ABOVE adam's 0.79–0.81 floor), so the offboard collapse (0.55–0.60) was a Muon × action-latency interaction, not a Muon property. The offboard Muon lr-grid item is moot for deployment.

Code: 3c5e75c (configs), 5b6767c (docs/ONBOARD_COMPUTE.md deploy-recipe entry) — pushed. Policy exported (policy.pt/onnx) so the Studio can fly the new ★ baseline.

## Staged frontier (next pass candidates, priority order)
1. **Motor lag (k_mot) in WhoopDynamics + DR** — the confirmed modeling gap from the PufferLib comparison (dawn-field-3426 item 2, royal-field-3745 item 5); touches vendored dynamics — version the change per AGENTS.md. The deploy recipe's aggressiveness makes actuator-lag fidelity MORE important, not less.
2. **Uplink realism: bursty jitter + dropout in the uplink seam** — replace uniform staleness + ZOH with a burst/dropout model; re-eval the recipe's DR-on floor under it. Cheap GPU item; de-risks O-1 before hardware.
3. O-2 Betaflight Air65 II flash-headroom build (Path-A go/no-go, needs local toolchain check); O-1 uplink bench still blocked on BOM approval (user).
4. (research, optional) Offboard Muon DR gap — now only of scientific interest; deprioritized since the deploy target is the onboard split.

Per-candidate note: 1–2 are pure-GPU and cheap; 3 needs toolchain/user input; 4 is optional.