#!/usr/bin/env python3
"""Put the hand-authored reference and the trained policy in ONE picture.

``scripts/reference_maneuver.py`` renders the trajectory we *want*; ``scripts/eval.py --record``
renders what a policy actually *did*. Rendering them as two separate clips and eyeballing them side
by side is the obvious thing and it is the wrong thing: ``--preset hero``'s follow rig derives its
camera from each replay's **own** track, so a policy that falls out of the sky gets chased down by
its own camera and lands in frame looking composed. The two clips are individually honest and the
comparison between them is not.

So this merges them into a **single replay with two drones** — the reference as ``drones[0]``, the
policy as ``drones[1]`` — and lets the existing renderer draw both. That needs **no renderer work**:
``web/studio/playback.js`` has drawn the v2 ``episodes[].drones[]`` group schema since the swarm
tasks, and ``web/capture/`` imports it verbatim. The merged replay is an ordinary replay; the Studio
plays it, ``scripts/capture_video.py`` renders it, and ``--preset hero`` still applies.

Two deliberate choices make the comparison honest rather than flattering:

* **The reference is the camera subject.** ``playback.js::heroTrackIndex`` picks, for a gateless
  task, the drone with the lowest mean distance to its own ``scene.target``, falling back to track 0
  when no track has one. The overlay therefore carries **no ``scene`` channel at all** and the
  reference — written first — deterministically wins. The camera flies the **ideal** trajectory and
  the policy is seen deviating from it; point the camera at the policy instead and every failure
  quietly re-centres itself. (Dropping ``scene`` is also what makes the picture legible: the
  follow-task target marker is a metre-scale sphere, and with the camera sitting on the marker it
  fills the entire frame.)
* **Neither track is padded.** A policy that terminates early (crash / early-abort) simply stops,
  while the reference plays on. The gap where the policy used to be is the result.

Alongside the overlay it writes the numbers, because the video shows *that* they diverge and the
chart shows *where*: per-channel error against time with the reference's own phase bands, so
"it never completes the COAST" is legible rather than inferred.

    uv run python scripts/reference_vs_policy.py \
        --policy runs/reference_track_flip/replay.json.gz \
        --reference runs/reference/flip_roll_z09_deployable/reference.json \
        --out runs/reference_track_flip/vs_reference --video
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from neural_whoop.reference.track import _rotmat_xyzw, load_reference_track  # noqa: E402
from neural_whoop.viz.replay import RunRecorder, load_run  # noqa: E402


#: True airframe footprint (m), tip to tip — what ``--preset hero`` scales the glyph to.
AIRFRAME_M = 0.082
#: ``hero``'s resting subject height in NDC (negative sits the subject below centre).
HERO_SUBJECT_Y = -0.06


#: Glyph exaggeration for the overlay. The true 82 mm airframe against a divergence of order 1 m
#: is an 11:1 ratio, so a frame containing both drones renders each at ~3 % of frame height (~30 px
#: at 1080) — too small to read which way either one is rotating, which is most of what the clip is
#: for. Drawing the airframe larger is what the Studio already does (~7x) for the same reason.
#: POSITIONS ARE UNTOUCHED: only the glyph is scaled, so every gap you see is the real gap.
GLYPH_SCALE = 3.0


def derive_drone_frac(separation_m: float, *, glyph_scale: float = 1.0,
                      margin: float = 1.15) -> float:
    """``--drone-frac`` that keeps BOTH drones in frame, derived from their worst separation.

    ``--preset hero`` frames a single subject: it holds the airframe at 22 % of the frame height,
    which spans ~0.37 m of world — a tenth of what an overlay needs. Rather than eyeball a number
    per clip (the failure mode ``docs/REFERENCE_MANEUVER.md``'s video contract exists to prevent),
    derive it: the follow rig parks the subject at NDC ``HERO_SUBJECT_Y``, so a drone ``sep`` metres
    away sits at ``HERO_SUBJECT_Y - sep / (frame_height / 2)`` and has to stay inside |NDC| < 1
    once padded by the airframe's own angular radius.

    Everything else still comes from ``hero``. Only the framing room is clip-dependent, because
    only it depends on a quantity — how badly the policy diverges — that is the result itself.
    """
    pad_ndc = 0.08 * glyph_scale        # the drawn airframe's own half-width, in NDC
    room = max(0.15, 1.0 - abs(HERO_SUBJECT_Y) - pad_ndc)
    frame_height = margin * 2.0 * max(separation_m, 1e-3) / room
    return round(AIRFRAME_M * glyph_scale / frame_height, 4)


def _rpy_from_quat(q: np.ndarray) -> np.ndarray:
    """ZYX euler (roll, pitch, yaw) from real-last quaternions, matching DiffAero's convention."""
    R = _rotmat_xyzw(q)
    pitch = np.arcsin(np.clip(-R[:, 2, 0], -1.0, 1.0))
    roll = np.arctan2(R[:, 2, 1], R[:, 2, 2])
    yaw = np.arctan2(R[:, 1, 0], R[:, 0, 0])
    return np.stack([roll, pitch, yaw], axis=-1)


def _episode_tracks(ep: dict) -> list[dict]:
    """The drone tracks of an episode, whether it uses the v2 group schema or the v1 flat one."""
    if isinstance(ep.get("drones"), list) and ep["drones"]:
        return ep["drones"]
    return [{"drone": ep.get("drone", 0), "dr": ep.get("dr"),
             "summary": ep.get("summary", {}), "frames": ep.get("frames", [])}]


def build_overlay(
    policy_replay: Path,
    reference_json: Path,
    *,
    episode: int = 1,
    exclude_phases: tuple[str, ...] = ("CLIMB", "HOVER", "LAND"),
) -> tuple[dict, dict]:
    """Merge one policy episode with its reference into a 2-drone replay document.

    Returns ``(replay_dict, comparison)`` — the merged document and the numbers behind it.
    """
    run = load_run(policy_replay)
    meta = dict(run["meta"])
    dt = float(meta["dt"])

    eps = run["episodes"]
    match = [e for e in eps if int(e.get("index", -1)) == episode]
    if not match:
        raise SystemExit(
            f"episode {episode} not in {policy_replay} (have "
            f"{[e.get('index') for e in eps]})"
        )
    ep = match[0]
    pol = _episode_tracks(ep)[0]
    pol_frames = pol["frames"]
    if not pol_frames:
        raise SystemExit(f"episode {episode} of {policy_replay} has no frames")

    track = load_reference_track(reference_json, dt=dt, exclude_phases=exclude_phases)

    # --- Align the reference onto THIS episode's station. -------------------------------------
    # reference_track jitters the maneuver's world placement per episode (station_jitter_*), and
    # publishes the resulting reference pose as scene.target. Anchoring on it means a jittered
    # training episode overlays correctly too, not just the zero-jitter eval twin.
    scene0 = pol_frames[0].get("scene") or {}
    if "target" in scene0:
        offset = np.asarray(scene0["target"], dtype=float) - track.pos[0]
    else:
        offset = np.zeros(3)
    ref_pos = track.pos + offset

    n_ref = track.n_steps
    n_pol = len(pol_frames)
    n_cmp = min(n_ref, n_pol)

    # --- The reference as a drone track. -------------------------------------------------------
    rpy = _rpy_from_quat(track.quat)
    t0 = float(pol_frames[0]["t"])
    ref_frames = [
        {
            "t": t0 + i * dt,
            "step": i + 1,
            "pos": ref_pos[i],
            "quat": track.quat[i],
            "rpy": rpy[i],
            "vel": track.vel[i],
            "angvel": track.omega[i],
            # act-v2 is normalized [-1,1]; the reference's authored command is in DiffAero units,
            # so only action_diffaero is meaningful here. Emit the authored thrust + rate command
            # and leave the normalized slot at the same thrust for a v1 reader's benefit.
            "action": [float(track.normed_thrust[i]), *[float(v) for v in track.rate_cmd[i]]],
            "action_diffaero": [float(track.normed_thrust[i]),
                                *[float(v) for v in track.rate_cmd[i]]],
            "reward": 0.0,
            "cum_reward": 0.0,
            "gate_idx": 0,
            "dist_to_gate": 0.0,
            "laps": 0,
            # No `scene`: see the module docstring. It would put a metre-scale target marker on the
            # camera's own subject, and its absence is what makes track 0 the hero.
        }
        for i in range(n_ref)
    ]

    # --- The policy track, with its own `scene` dropped for the same two reasons. ---------------
    # Trimmed to the reference window: a policy that SURVIVES the maneuver keeps flying to the
    # episode cap (the flip's eval runs 499 steps against a 110-step reference), and those extra
    # steps are the trivial hold-final-state tail, not the maneuver. Leaving them in would pad the
    # clip with 78 % hover, and — the reason it matters beyond aesthetics — averaging a metric over
    # them is what makes a surviving policy look better than a crashed one for the wrong reason.
    pol_out = [{k: v for k, v in fr.items() if k != "scene"} for fr in pol_frames[:n_ref]]

    # --- The numbers. ---------------------------------------------------------------------------
    p_pos = np.asarray([f["pos"] for f in pol_frames[:n_cmp]], dtype=float)
    p_quat = np.asarray([f["quat"] for f in pol_frames[:n_cmp]], dtype=float)
    p_omega = np.asarray([f["angvel"] for f in pol_frames[:n_cmp]], dtype=float)
    p_thr = np.asarray([f["action_diffaero"][0] for f in pol_frames[:n_cmp]], dtype=float)

    pos_err = np.linalg.norm(p_pos - ref_pos[:n_cmp], axis=-1)
    dot = np.abs(np.sum(p_quat * track.quat[:n_cmp], axis=-1)).clip(0.0, 1.0)
    att_err = np.degrees(2.0 * np.arccos(dot))
    rate_err = np.linalg.norm(p_omega - track.omega[:n_cmp], axis=-1)

    labels = list(track.phase_labels)
    reached = sorted({int(v) for v in track.phase[:n_cmp]})
    all_ph = sorted({int(v) for v in track.phase})

    comparison = {
        "policy_replay": str(policy_replay),
        "reference": str(reference_json),
        "episode": episode,
        "dt": dt,
        "reference_steps": n_ref,
        "policy_steps": n_pol,
        # How much of the MANEUVER the policy stayed alive for. Capped at 1.0: a surviving policy
        # runs on to the episode cap, and "450 % complete" is not a thing.
        "completed_fraction": round(min(n_pol, n_ref) / n_ref, 4),
        "policy_ended": ep.get("summary", {}).get("ended"),
        "compared_steps": n_cmp,
        # Over the steps the policy actually flew — NOT over the reference, so a policy that dies
        # early cannot buy a good average by simply not being measured on the hard part.
        "pos_err_m_mean": round(float(pos_err.mean()), 4),
        "pos_err_m_final": round(float(pos_err[-1]), 4),
        "att_err_deg_mean": round(float(att_err.mean()), 4),
        "rate_err_rps_mean": round(float(rate_err.mean()), 4),
        "phases_in_reference": [labels[i] for i in all_ph],
        "phases_reached": [labels[i] for i in reached],
        "phases_never_reached": [labels[i] for i in all_ph if i not in reached],
        "peak_thrust_policy": round(float(p_thr.max()), 4),
        "peak_thrust_reference": round(float(track.normed_thrust.max()), 4),
        "peak_climb_policy_m": round(float(p_pos[:, 2].max() - ref_pos[0, 2]), 4),
        "peak_climb_reference_m": round(float(ref_pos[:, 2].max() - ref_pos[0, 2]), 4),
    }

    # Worst on-screen separation, over the WHOLE clip: a track that ends early is held at its last
    # frame by the renderer, so the gap keeps opening after the policy dies and that is exactly the
    # part the framing has to accommodate.
    all_pol = np.asarray([f["pos"] for f in pol_frames], dtype=float)
    held = np.vstack([all_pol, np.repeat(all_pol[-1:], max(0, n_ref - n_pol), axis=0)])[:n_ref]
    sep = np.linalg.norm(held - ref_pos[:n_ref], axis=-1)
    comparison["max_separation_m"] = round(float(sep.max()), 4)
    comparison["glyph_scale_x"] = GLYPH_SCALE
    comparison["render_scale_m"] = round(AIRFRAME_M * GLYPH_SCALE, 4)
    comparison["drone_frac"] = derive_drone_frac(float(sep.max()), glyph_scale=GLYPH_SCALE)

    # --- Assemble. -----------------------------------------------------------------------------
    meta["source"] = "reference_vs_policy overlay"
    meta["overlay"] = {
        "drone_0": "hand-authored reference (the trajectory we WANT)",
        "drone_1": "trained policy",
        "camera_subject": "drone_0 (the reference) — so deviation is visible, see script docstring",
        "reference_file": str(reference_json),
        "policy_file": str(policy_replay),
    }
    scene_info = dict(meta.get("scene_info") or {})
    scene_info["target_label"] = "reference pose (the trajectory we WANT)"
    meta["scene_info"] = scene_info

    rec = RunRecorder(meta)
    rec.add_group_episode(
        index=1,
        gates=ep.get("gates") or [],
        tracks=[
            # The reference is a GHOST: translucent, plain-coloured trail, no shadow. It is the
            # thing being tracked, not a second flight, and the solid airframe should read as the
            # policy. `style` is an additive replay render hint (viz/replay.py).
            {"drone": 0, "dr": None,
             "summary": {"steps": n_ref, "ended": "reference", "total_reward": 0.0},
             "style": {"ghost": {"opacity": 0.3, "color": 0x8fd4ff}},
             "frames": ref_frames},
            {"drone": 1, "dr": pol.get("dr"),
             "summary": dict(pol.get("summary", {})), "frames": pol_out},
        ],
    )
    return rec.to_dict(), comparison


def plot_comparison(
    policy_replay: Path, reference_json: Path, comparison: dict, out: Path, *, episode: int = 1
) -> Path:
    """Per-channel error against time, banded by the reference's own phases."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    run = load_run(policy_replay)
    ep = [e for e in run["episodes"] if int(e.get("index", -1)) == episode][0]
    pol_frames = _episode_tracks(ep)[0]["frames"]
    dt = float(run["meta"]["dt"])
    track = load_reference_track(reference_json, dt=dt)

    n = min(track.n_steps, len(pol_frames))
    t_ref = np.arange(track.n_steps) * dt
    t = t_ref[:n]

    p_pos = np.asarray([f["pos"] for f in pol_frames[:n]], dtype=float)
    p_quat = np.asarray([f["quat"] for f in pol_frames[:n]], dtype=float)
    p_thr = np.asarray([f["action_diffaero"][0] for f in pol_frames[:n]], dtype=float)
    scene0 = pol_frames[0].get("scene") or {}
    offset = (np.asarray(scene0["target"], dtype=float) - track.pos[0]
              if "target" in scene0 else np.zeros(3))
    ref_pos = track.pos + offset

    pos_err = np.linalg.norm(p_pos - ref_pos[:n], axis=-1)
    dot = np.abs(np.sum(p_quat * track.quat[:n], axis=-1)).clip(0.0, 1.0)
    att_err = np.degrees(2.0 * np.arccos(dot))

    fig, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=True)
    labels = list(track.phase_labels)
    phase = track.phase.astype(int)
    colors = plt.get_cmap("Pastel1").colors

    for ax in axes:
        prev, start = phase[0], 0.0
        for i in range(1, track.n_steps + 1):
            if i == track.n_steps or phase[i] != prev:
                ax.axvspan(start, t_ref[min(i, track.n_steps - 1)],
                           color=colors[prev % len(colors)], alpha=0.45, lw=0)
                if i < track.n_steps:
                    prev, start = phase[i], t_ref[i]
        if len(pol_frames) < track.n_steps:
            ax.axvline(t[-1], color="crimson", lw=2.0, ls="--")

    # Altitude — the channel where "it never completes" is most legible.
    axes[0].plot(t_ref, ref_pos[:, 2], color="#1a1a1a", lw=2.4, label="reference (authored)")
    axes[0].plot(t, p_pos[:, 2], color="#d62728", lw=2.0, label="policy")
    axes[0].set_ylabel("altitude (m)")
    axes[0].legend(loc="upper right", fontsize=9)
    ended = comparison.get("policy_ended")
    axes[0].set_title(
        f"reference vs policy — {Path(reference_json).parent.name}   "
        f"(policy flew {comparison['completed_fraction']:.0%} of the maneuver, ended: {ended})",
        fontsize=11,
    )

    # Collective thrust — separates "could not" from "would not".
    axes[1].plot(t_ref, track.normed_thrust, color="#1a1a1a", lw=2.4, label="reference command")
    axes[1].plot(t, p_thr, color="#d62728", lw=2.0, label="policy command")
    lim = run["meta"].get("action_limits", {}).get("max_thrust_normed")
    if lim:
        axes[1].axhline(float(lim), color="#777", ls=":", lw=1.5,
                        label=f"act-v2 ceiling ({lim:g})")
    axes[1].set_ylabel("normed thrust\n(1.0 = hover)")
    axes[1].legend(loc="upper right", fontsize=9)

    axes[2].plot(t, pos_err, color="#d62728", lw=2.0, label="position error (m)")
    ax2 = axes[2].twinx()
    ax2.plot(t, att_err, color="#1f77b4", lw=2.0, label="attitude error (deg)")
    axes[2].set_ylabel("position error (m)", color="#d62728")
    ax2.set_ylabel("attitude error (deg)", color="#1f77b4")
    axes[2].set_xlabel("time through the tracked maneuver (s)")

    # Name the phase bands once, along the bottom.
    prev, start = phase[0], 0.0
    for i in range(1, track.n_steps + 1):
        if i == track.n_steps or phase[i] != prev:
            mid = 0.5 * (start + t_ref[min(i, track.n_steps - 1)])
            axes[2].annotate(labels[prev], xy=(mid, 0), xycoords=("data", "axes fraction"),
                             xytext=(0, 4), textcoords="offset points",
                             ha="center", fontsize=8, color="#333")
            if i < track.n_steps:
                prev, start = phase[i], t_ref[i]

    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130)
    plt.close(fig)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--policy", required=True, type=Path, help="policy replay.json.gz")
    ap.add_argument("--reference", required=True, type=Path, help="the reference.json DATA artifact")
    ap.add_argument("--out", required=True, type=Path, help="output directory")
    ap.add_argument("--episode", type=int, default=1, help="which hero episode (1-based)")
    ap.add_argument("--video", action="store_true",
                    help="also render the overlay MP4 through the standard hero contract")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    doc, comparison = build_overlay(args.policy, args.reference, episode=args.episode)

    overlay = args.out / "overlay.json.gz"
    with gzip.open(overlay, "wt", encoding="utf-8") as fh:
        json.dump(doc, fh)
    print(f"[overlay] {overlay}  ({len(doc['episodes'][0]['drones'])} drones)")

    (args.out / "comparison.json").write_text(json.dumps(comparison, indent=2))
    for k in ("completed_fraction", "policy_ended", "pos_err_m_mean", "att_err_deg_mean",
              "peak_thrust_policy", "peak_thrust_reference",
              "peak_climb_policy_m", "peak_climb_reference_m", "phases_never_reached",
              "max_separation_m", "drone_frac"):
        print(f"  {k:26s} {comparison[k]}")

    try:
        chart = plot_comparison(args.policy, args.reference, comparison,
                                args.out / "tracking_error.png", episode=args.episode)
        print(f"[chart]   {chart}")
    except ImportError as exc:
        print(f"[chart]   skipped (needs the viz extra): {exc}")

    if args.video:
        import subprocess
        mp4 = args.out / "vs_reference.mp4"
        # `hero` minus its single-subject framing: everything else (follow rig, fogged cyclorama,
        # steep key, true-scale airframe) is the standard look, and an explicit flag beats the
        # preset. reference.video's pinned invocation is deliberately NOT reused — it is the
        # contract for a one-drone concept shot and must stay untouched.
        cmd = [sys.executable, str(Path(__file__).parent / "capture_video.py"),
               "--replay", str(overlay), "--out", str(mp4),
               "--preset", "hero", "--width", "1080", "--height", "1080",
               "--drone-frac", str(comparison["drone_frac"]),
               "--scale", str(comparison["render_scale_m"])]
        print("[video]   " + " ".join(cmd))
        subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
