---
node_id: a1a3e826-3b6d-57ff-9706-bb078ce5283d
slug: bitter-sun-1558
title: 'Onboard-only autonomy — literature synthesis: learned gate-relative estimation beats classical VIO; a $4-ToF ladder to hover/racing/acro/swarm (2026-07-07)'
created_at: '2026-07-07T14:23:36.818053+00:00'
parents:
- aged-wildflower-8839
summary: 'Deep-research synthesis (15 primary sources, 73 adversarially-verified claims) answering how a stock analog-FPV whoop (mono cam + IMU + ESP32 + offboard laptop, NOTHING off-drone for sensing) reaches hover/racing/acro/swarm. Headline finding: the systems that WIN do not run classical dense VIO off the camera — they run a LEARNED gate/landmark detector + a dynamics-model/IMU, fused (relative-to-landmarks, monocular, robust to bad video). Proofs: MonoRace (TU Delft 2026, arXiv 2601.15222) beat 3 human FPV world champions with a single monocular cam+IMU + learned gate segmentation + drone model + EKF (NOT VIO), 100 km/h; the 72 g ''Trashcan'' (arXiv 1905.10110) did whoop-mass onboard monocular racing via visual model-predictive localization, explicitly avoiding VIO/SLAM; Swift (Nature 2023) is onboard-only but its VIO half used a STEREO T265 (not monocular) — its gate-detector half is the transferable part. Classical monocular VIO is the fragile path (scale unobservable — SVO ICRA14; fails at racing speed — UZH-FPV ICRA19; heavy on weak CPUs — Delmerico ICRA18) BUT the offboard-laptop design rescues it (SVO 300 fps on laptop; OpenVINS 11.4 ms/~87 Hz), turning compute into a non-issue and leaving link latency (already modeled) as the real enemy. Per-capability verdict: velocity-damped hover = do-now, no HW (FPV optical flow + IMU on laptop); rock-solid metric hover = one ~$4 VL53L1x ToF (resolves monocular scale); gated racing = near-term (MonoRace/Trashcan recipe, monocular, proven at whoop mass); open-loop acro = do-now IMU-only via teacher-student privileged learning trained in sim (Learning High-Speed Flight, Sci Robotics 2021); gateless apartment racing = frontier (the Quest scan is the map); swarm = longest pole, cheap onboard path is UWB peer-ranging (~$8/drone, constraint-compatible, arXiv 2003.05853). Recommended ladder adds across ALL capabilities: one ~$4 ToF + one ~$8 UWB module/drone. North-star bet: an end-to-end world-model policy (SkyDreamer, arXiv 2510.14783 — world model as implicit state estimator) consuming the FPV image + IMU -> CTBR, trained in DiffAero + apartment scan with analog-video-degradation DR — one generalized policy for hover/racing/acro. Full cited report + sources attached.'
origin:
  backend: flywheel
  node_id: a1a3e826-3b6d-57ff-9706-bb078ce5283d
  slug: bitter-sun-1558
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: abb45d86-2174-593a-8b27-2519ff5cc646
  slug: bitter-salad-4087
  revision: 0
  pushed_at: '2026-08-09T21:27:48+00:00'
  content_sha256: dadc90eb4726d510088413f449e684dcacd36674e5005ed73909a1b882c12925
---
# Onboard-only tiny-whoop autonomy — what the field actually does, and our cheapest path

**Framing.** Prompted by the horizontal drift exposed in the parent flight (`aged-wildflower-8839`): a blind IMU-only policy has no position/velocity feedback and cannot station-keep. User constraints for the fix: (1) NOTHING off the drone for sensing (offboard laptop COMPUTE is fine); (2) cheap/accessible hardware; (3) as close to stock (analog FPV cam + IMU + Betaflight FC) as possible; (4) research project — creative > safe-but-expensive; goal = a generalized but high-performing platform (hover, apartment gate racing, acro, swarm). This node synthesizes a 5-angle deep-research pass: 15 primary sources -> 73 falsifiable claims -> 3-vote adversarial verification (0 load-bearing claims refuted).

## The finding that reframes the problem
**The systems that win do NOT run classical dense VIO off the camera. They run a learned gate/landmark detector + a dynamics model / IMU, fused — relative-to-landmarks, not absolute-from-pixels.** Cheap, robust to bad video, monocular. Three verified proofs:
- **MonoRace** (TU Delft, arXiv 2601.15222, Jan 2026): beat **three human FPV world champions** (A2RL Abu Dhabi 2025) with a **single monocular rolling-shutter camera + IMU**, up to **100 km/h**. State estimation = learned gate **segmentation** (GateNet U-Net) + a **drone dynamics model** fused with IMU in an **EKF** — *explicitly not classical VIO* — + offline refinement from known gate geometry. Closest existing system to our platform.
- **72 g 'Trashcan'** (TU Delft, arXiv 1905.10110, JFR 2020): **whoop-class 72 g** drone, one monocular camera, fully-onboard gate racing via **Visual Model-Predictive Localization** (fuse gate detections with model-dynamics), 'computationally more efficient than VIO and SLAM.' Proof the recipe scales to whoop mass.
- **Swift** (Kaufmann et al., **Nature 2023**): champion-beater, **onboard-only** — CNN **gate-corner detector** -> camera resectioning vs a known track map -> **Kalman-fused with VIO to correct VIO drift**; MLP 2×128 -> **collective-thrust + body-rates** (our exact CTBR contract). *Caveat:* Swift's VIO ran on a RealSense **T265 = STEREO fisheye + IMU, NOT monocular** — so Swift proves onboard-only racing, and its *gate-detector half* is what transfers to our monocular-analog stack, not its VIO half.

**So for racing the durable, cheap, monocular path is learned relative gate/landmark detection + model/IMU fusion — proven down to 72 g.** Classical VIO is the fragile part, and we can lean on it far less than compute-bound onboard systems had to.

## Why classical monocular VIO is fragile — but the laptop rescues it
- **Monocular scale unobservable** (SVO, Forster ICRA 2014): 'a camera is only an angle-sensor... impossible to obtain the scale... scale drift... motivate the need for a camera-IMU system.' A monocular-only hover holds *zero velocity*, not an *absolute point*, absent a scale anchor.
- **VIO breaks at racing speed** (UZH-FPV, Delmerico ICRA 2019): SOTA VIO (VINS-Fusion, Ultimate-SLAM) **failed on many high-speed sequences**.
- **VIO is heavy on weak compute** (Delmerico & Scaramuzza ICRA 2018): VINS-Mono most accurate but ~150-250% of a core; some pipelines wouldn't converge on a weak board. Onboard VIO ~13-20 Hz (OF-VINS-Mono 2024).
- **...but OFFBOARD on a laptop this evaporates:** SVO **>300 fps on a laptop** (3.04 ms/frame) vs 55 fps embedded; OpenVINS **11.4 ms / ~87 Hz** on an edge GPU (A2RL/KAIST, arXiv 2512.20475). Our architecture already runs the policy on the laptop -> we get the *laptop* VIO regime. The only added cost is link latency — the enemy we already model and just improved.

## Per-capability honest verdict
- **(a) Hover.** Velocity-damped (stops the drift, holds a loose column) = **do-now, no HW**: FPV optical flow (laptop) de-rotated by IMU -> body velocity -> damp. Rock-solid metric hold = **one ~$4 VL53L1x ToF** (downward, I²C on the ESP32) to resolve monocular scale + give altitude. (This is what the ~$10 PMW3901+VL53L1x indoor-position decks do.)
- **(b) Racing.** Gated = **near-term**: learned gate detector on the FPV feed + model/IMU fusion = the MonoRace/Trashcan recipe, monocular, proven at whoop mass. Gateless map-relative apartment racing = **frontier** (visual relocalization vs a prior map) — the **Quest apartment scan** is exactly that map (trains sim + serves as localization prior).
- **(c) Acro.** Flips/rolls/power-loops are proprioceptive — **do-now, IMU-only**, via teacher-student **privileged learning trained entirely in sim, zero-shot to real** (Learning High-Speed Flight in the Wild, Sci Robotics 2021; Deep Drone Acrobatics, RSS 2020). Point-anchored tricks (pendulum, donuts around a spot) need the (a) position loop. **The most immediately achievable ambitious goal we have.**
- **(d) Swarm.** Longest pole. Cheap onboard relative localization = **UWB peer-to-peer ranging** (~$8/drone, drone-to-drone — does NOT violate constraint 1, only room-anchors would); TU Delft infra-free swarm (shushuai3, arXiv 2003.05853) fuses UWB range + relative velocity. Vision-based mutual detection = research-grade.

## Recommended ladder (cheapest-first)
| Rung | Add | Cost/mass | Unlocks | Confidence |
|---|---|---|---|---|
| 0 | FPV optical flow (laptop) + IMU | $0 | velocity-damped hover; open-loop acro | High |
| 1 | VL53L1x ToF (downward) | ~$4, <1 g | metric hover (scale + altitude) | High |
| 2 | Learned gate detector (laptop) + model fusion | $0 HW | gated racing, anchored tricks | Med-High |
| 3 | Quest scan -> sim map + end-to-end/world-model policy | $0 | gateless apartment racing, one-policy platform | Frontier |
| 4 | UWB peer-ranging module/drone | ~$8 ea | swarm relative localization | Med |

Everything reuses the current stack (analog FPV + IMU + ESP32 + laptop + DiffAero + RL). The only physical adds across all four capabilities: **one ~$4 ToF** and (swarm) **one ~$8 UWB per drone.**

## The creative frontier bet
**SkyDreamer** (TU Delft, arXiv 2510.14783, Oct 2025): first **end-to-end vision->motor-command RL** racing, built on a model-based RL **world model that 'effectively functions as an implicit state and parameter estimator'** — no explicit VIO. Sim-to-real works even on *poor-quality* segmentation masks (our noisy analog feed). Unifying north star: **one policy consuming the FPV image (or a learned segmentation) + IMU -> CTBR, trained in DiffAero + the apartment scan with DR over analog-video degradation (noise, rolling shutter, dropout, latency)** — the world model learns the estimator we'd otherwise hand-build; subsumes hover/racing/acro under one architecture, swarm adds the relative-localization channel.

## Verdict / honesty
**Direction node (idea), not an empirical result.** Strongest evidence-backed recommendations: (1) drop the assumption that we need VIO — go gate/landmark-relative + model, the proven monocular path; (2) a single ~$4 ToF is the highest-leverage onboard add (metric hover); (3) open-loop acro is startable now with zero new hardware; (4) the offboard laptop is an asset, not a liability, for perception compute. Honesty: MonoRace/Swift/SkyDreamer ran heavier compute (Jetson-class) and better cameras than an analog whoop feed — the analog-video-degradation gap is real and is the sim-to-real DR problem to own; gateless apartment racing and vision-only swarm remain research frontiers. Provenance: the deep-research workflow's auto-synthesis step returned a stub; this node was reconstructed from the run's 73 adversarially-verified claim records.

## Lineage
Parent: **aged-wildflower-8839** (the flight that exposed horizontal drift and motivated the sensing question). Feeds the deferred **apartment-scan / Quest** idea (docs/SIM2REAL.md backlog) — now evidence-backed as the map for both training and localization. Sets up future perception/estimation work (a learned gate detector; a ToF-anchored hover; an end-to-end world-model policy).