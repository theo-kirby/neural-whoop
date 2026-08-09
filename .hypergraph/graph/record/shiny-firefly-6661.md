---
node_id: 43ddf2e8-6f31-5542-8165-1bf7dd927db9
slug: shiny-firefly-6661
title: 'Hypothesis: the 2.5 rad/s gyro-noise wall is aliased frame vibration, hence software-reducible — there is a learnability ceiling σ* the stock bridge can get under'
created_at: '2026-07-06T21:25:29.008936+00:00'
parents:
- delicate-credit-2979
- rough-art-1658
summary: 'The 2.5 rad/s gyro-noise amplitude that sinks blind hover is aliased frame vibration at 50 Hz MSP sampling, not intrinsic sensor error — so the amplitude at the policy input is software-controllable (L1 bridge oversample-average -> 0.5x, L2 matched EMA, L3 policy memory) on strictly stock hardware. Predicts a learnability ceiling sigma*: R1-recipe training at sigma < sigma* recovers M1>=91.6% and M2(sigma)>=80%. Test = dose-response arms d50 (1.25/1.1/0.75, running, commit ad7e8a1) then d25 if needed. Falsifier: d25 (4x reduction, the plausible software limit) still failing M1 = the software-only line is RED. Pro: R-ladder hold time was graded (2.96->5.18->12.84 s). Con: M2 worsened down that ladder.'
origin:
  backend: flywheel
  node_id: 43ddf2e8-6f31-5542-8165-1bf7dd927db9
  slug: shiny-firefly-6661
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 3fd48f93-25c7-596d-acbf-5879d38ee254
  slug: calm-breeze-0519
  revision: 0
  pushed_at: '2026-08-09T21:27:34+00:00'
  content_sha256: 2ba5f85eae68701c95812657c5c50754302bb7e7734b66eaa24527bfcf8b60d7
---
# The amplitude is not a law of nature — it is a sampling artifact the software stack controls

**Claim.** The R-ladder's final attribution (rough-art-1658) — "the honest gyro-noise amplitude itself sinks blind hover" — is correct *as measured*, but the measured amplitude is not irreducible. Per `docs/SIM2REAL.md` (2026-07-06 flight campaign): the ±145°/s (≈2.5 rad/s) sd was measured **from frame vibration** during calm hover, sampled at ~50 Hz over the MSP bridge. Physically that is narrowband prop/motor vibration (hundreds of Hz) aliased by a slow sampler — the *true attitude motion* underneath is tiny (145°/s at ~300 Hz ≈ ±0.08° excursion). Betaflight's own kHz rate loop flies through the same sensor happily; only our 50 Hz single-sample reads are drowned.

**Therefore, testable predictions:**
1. There exists a **learnability ceiling σ***: training the R1 recipe at gyro noise sd σ < σ* recovers M1 ≥ 91.6% clean survival AND M2(σ) ≥ 80% at its own amplitude. The R-ladder only established σ* < 2.5 rad/s; it never probed below.
2. **Software levers reach below σ*** with zero new hardware:
   - **L1 oversample-average (bridge):** poll MSP_RAW_IMU at ~200 Hz (median RTT 2.41 ms bench-measured) and box-average 4 samples per policy step → sd/√4 = 0.5× *if inter-sample independent at 5 ms spacing* (unvalidated — aliased narrowband noise decorrelates fast, but must be bench-measured).
   - **L2 EMA/LPF (host):** matched train/deploy obs filter → further reduction at the cost of phase lag the policy trains against.
   - **L3 memory (policy):** deeper obs_stack / recurrence → learned filtering; offboard execution means capacity is not binding.

**Test (dose-response, cheap-first).** Arm `d50` (commit ad7e8a1, `configs/hover_blind_air65_d50.yaml`): exact R1 recipe, ONE factor changed — gyro noise sd 2.5/2.2/1.5 → 1.25/1.1/0.75 (attitude noise and gyro DC bias unchanged; averaging cannot remove bias, so it stays honestly at 0.05 rad/s). If d50 clears both bars → σ* ≥ 1.25 rad/s and the L1 lever ALONE closes the gap → flagship candidate + a bench-validation checklist (poll rate, independence). If d50 fails → `d25` brackets σ* lower; σ* below ~0.6 rad/s would demand L2/L3 stacking or concede RED.

**Falsifier.** If even d25 (0.625 rad/s — 4× reduction, the plausible limit of L1+modest L2) fails M1, the sink is not amplitude-gated in the reachable range and the software-only line is honestly RED.

**Prior evidence pro:** the R-ladder's monotone hold-time progression (2.96→5.18→12.84 s median as levers stack) shows the failure is graded, not a cliff — consistent with an amplitude threshold nearby. **Prior evidence con:** M2 got *worse* down the R-ladder (4.0→3.2→0.9%), warning that levers which stretch the sink can still lose deploy robustness.

**Lineage.** Parents: control contract `delicate-credit-2979` (this campaign) + `rough-art-1658` (the amplitude attribution this operationalizes). The measured-amplitude provenance is muddy-hill-9397's flight campaign; the metric split is quiet-bonus-7296's.