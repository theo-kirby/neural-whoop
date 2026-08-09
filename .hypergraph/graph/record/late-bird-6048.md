---
node_id: 1ef7a91d-8fc0-57b3-84f6-d23c0f340f67
slug: late-bird-6048
title: 'Idea: off-drone hardware triage — accept FC-accel-over-MSP + ESP-NOW-if-jitter; decline NFC / stereo / ext-accel / WiFi-FTM / ESP-gamepad'
created_at: '2026-07-11T17:09:27.759801+00:00'
parents:
- fancy-rice-9295
- still-flower-6355
summary: 'A feasibility triage of the off-drone ideas so we don''t relitigate them. ACCEPT: read the FC accelerometer over MSP_RAW_IMU (msg 102) instead of adding an external accel module — better-mounted, calibrated, free (feeds the accel-in-obs hypothesis). CONDITIONAL: a ground ESP32 as a USB-CDC↔ESP-NOW dongle (ESP-NOW ~1-5 ms consistent vs WiFi-UDP buffering spikes) — build ONLY if flight logs show WiFi jitter actually hurting (data-driven; the link p99 regression is a candidate trigger). DECLINE: NFC (1-4 cm range, useless in flight); stereo/dual whoop cameras (one DVP per S3, no sync, no compute, blows mass margin); external accel module (redundant with the FC IMU); WiFi-FTM (~1-5 m indoor ≈ the whole 2-4 m arena — use the fiducial rig instead); ESP-side gamepad (radio contention). Idea/decision.'
origin:
  backend: flywheel
  node_id: 1ef7a91d-8fc0-57b3-84f6-d23c0f340f67
  slug: late-bird-6048
  revision: 1
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: f19c500d-0e5a-56ec-9f76-e81073c8bb62
  slug: damp-glade-2512
  revision: 0
  pushed_at: '2026-08-09T21:28:03+00:00'
  content_sha256: f86f4e6d2d7b624a545b14edce62eab082863010e1c9f2b7b66eea6e890bd4db
---
# Idea: off-drone hardware triage

Triage of the user's off-drone wishlist (ground ESP, NFC, accelerometer, dual cameras) + the gamepad radio question, grounded in a hardware-feasibility sweep. Recorded as a decision so these don't get relitigated.

## ACCEPT (do it)
- **FC accelerometer over MSP.** `MSP_RAW_IMU` (msg 102) returns acc(3)+gyro(3)+mag(3) at 50-100 Hz over the existing link. This is the enabler for the accel-in-obs hover hypothesis — no hardware, and strictly better than an add-on module (mounted+calibrated on the FC). Verify the acc scaling (~/512 g on typical BF setups) against our FC.

## CONDITIONAL (only if data says so)
- **Ground ESP32 = USB-CDC↔ESP-NOW dongle.** ESP-NOW is ~1-5 ms and consistent (no AP/DHCP/ARP) vs WiFi-UDP's ~2-15 ms with buffering spikes. The Mac can't speak ESP-NOW, so a ground ESP bridges serial↔ESP-NOW, removing the router from the loop and taming the tail. Also usable as an independent failsafe heartbeat. Build ONLY if `flight_report` link stats show WiFi jitter hurting — the Bench-session p99 doubling (137-170 ms) is exactly the kind of trigger to check first (confounded with in-process uvicorn/parallel-sim — do the CLI-vs-dashboard A/B before blaming WiFi).

## DECLINE (recorded, don't relitigate)
- **NFC** — 1-4 cm inductive range; nothing in flight. Landing-pad ID is better served by UDP self-announce.
- **Stereo / dual cameras on the whoop** — one DVP camera interface per S3, no inter-board frame sync, no stereo-matching compute budget, and two pods blow the 32 g mass margin. Dead end. (A single downward cam only makes sense as the already-decided XIAO Sense perception module, not for stereo.)
- **External accelerometer module** — redundant, worse-mounted/calibrated duplicate of the FC IMU. Drawer.
- **WiFi FTM (802.11mc) localization** — ~1-5 m indoor error ≈ the whole bench arena; RSSI worse. The fiducial mocap rig is the position ground-truth.
- **ESP-side (Bluepad32) gamepad** — BLE+WiFi share one S3 radio (MSP-link jitter), safety off-dashboard. Browser Web Gamepad API instead.

## Lineage
Parents: roadmap hub (Tier-3 + declines), and the 'one module' decision (XIAO Sense + ToF) — this triage is consistent with that: the Sense cam remains the perception master-key; none of these off-drone pieces displace it.