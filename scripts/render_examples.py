#!/usr/bin/env python3
"""Render the nine checked-in example clips — three maneuvers x three video kinds.

``render-examples/`` is the repo's answer to "show me what this looks like" without a GPU, a
policy checkpoint, or the ``capture`` extra. Nine MP4s, a ``README.md`` explaining the naming and
where each one came from, and a ``manifest.json`` recording every derived number.

The point of doing it from one script rather than nine commands is the framing. For each maneuver
this:

1. resolves the reference + policy inputs from :data:`EXAMPLE_SOURCES`;
2. calls ``reference_vs_policy.build_overlay`` **as a function** to merge them and, crucially, to
   measure ``max_separation_m`` — the worst on-screen gap between the ghost reference and the
   policy tracking it;
3. turns that one measurement into a :class:`~neural_whoop.video.framing.FramingPlan`;
4. renders all three of that maneuver's clips **with that single plan**.

Step 4 is the whole idea. The reference clip is then literally the comparison with the policy
removed — same camera path (the follow rig's subject is the reference in both), same airframe size,
same horizon — so the three clips can be read against each other. Framing each one at its own
"natural" size instead would show the same drone at three sizes and quietly break the comparison
the directory exists to support.

    uv run python scripts/render_examples.py                 # all nine, into runs/render_examples/
    uv run python scripts/render_examples.py --maneuver flip # just one maneuver's three
    uv run python scripts/render_examples.py --dry-run       # print the argv, render nothing
    uv run python scripts/render_examples.py --publish       # + 720p/CRF-26 copies into the repo

``runs/`` is gitignored, so a fresh clone has none of the inputs. Every missing one is reported
with the **exact command that produces it** rather than a FileNotFoundError.
"""

from __future__ import annotations

import argparse
import gzip
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from reference_vs_policy import build_overlay  # noqa: E402

from neural_whoop.video.framing import plan_framing  # noqa: E402
from neural_whoop.video.names import KIND_BLURBS, KINDS, MANEUVERS, video_filename  # noqa: E402
from neural_whoop.video.render import BASE_VIDEO_ARGS, render_video, video_command  # noqa: E402

#: Where the masters go. Gitignored; only the ``--publish`` transcodes are checked in.
MASTER_DIR = REPO_ROOT / "runs" / "render_examples"
#: The checked-in directory.
PUBLISH_DIR = REPO_ROOT / "render-examples"

#: 720x720 at CRF 26 — the whole set lands around 3-4 MB, which is a reasonable thing to put in a
#: git history. The 1080 masters stay in ``runs/``.
PUBLISH_SIZE = 720
PUBLISH_CRF = 26


class Source:
    """Where one maneuver's three clips come from, and how to rebuild a missing input."""

    def __init__(self, maneuver: str, *, run: str, reference: str, config: str, note: str):
        self.maneuver = maneuver
        self.run = REPO_ROOT / "runs" / run
        self.policy_replay = self.run / "replay.json.gz"
        self.reference_json = REPO_ROOT / "runs" / "reference" / reference / "reference.json"
        self.config = config
        self.note = note

    def missing(self) -> list[tuple[Path, str]]:
        """``[(path, the command that produces it)]`` for every input not on disk."""
        out = []
        if not self.reference_json.exists():
            out.append((self.reference_json, self.reference_command()))
        if not self.policy_replay.exists():
            out.append((self.policy_replay, self.policy_command()))
        return out

    def reference_command(self) -> str:
        return (f"uv run python scripts/reference_maneuver.py --maneuver {self.maneuver} "
                f"--out {self.reference_json.parent.relative_to(REPO_ROOT)}"
                + (" --z-entry 0.9" if self.maneuver == "flip" else "")
                + (" --deployable" if self.maneuver == "flip" else ""))

    def policy_command(self) -> str:
        return (f"uv run python scripts/eval.py --config configs/{self.config} "
                f"--from {(self.run / 'ckpt_final.pt').relative_to(REPO_ROOT)} --no-dr --record")


#: The three maneuvers' inputs.
#:
#: The flip's policy is **v2**, not the original ``reference_track_flip``: v2 is the arm that
#: actually completes the maneuver, and a comparison clip whose policy never reaches the second
#: phase shows a failure mode rather than a comparison.
#:
#: The orbit's reference is ``orbit_z_fixed``, generated after the 2026-08-01 rate-loop fix. Its
#: trajectory is byte-identical to ``orbit_z`` (verified: pos/quat/omega all equal) — the authoring
#: is pure numpy and never touched the simulator — and only ``verify.json``'s stability verdict
#: differs. Pointing at the post-fix artifact means the shipped clip's provenance chain doesn't
#: run through a file that says the maneuver was unflyable.
EXAMPLE_SOURCES = {
    "flip": Source(
        "flip", run="reference_track_flip_v2", reference="flip_roll_z09_deployable",
        config="reference_track_flip_v2_eval.yaml",
        note="the v2 arm — the one that completes the maneuver",
    ),
    "swing": Source(
        "swing", run="reference_track_swing", reference="swing_roll",
        config="reference_track_swing_eval.yaml",
        note="flatness-authored, no shoot; closes on its own start point at machine precision",
    ),
    "orbit": Source(
        "orbit", run="reference_track_orbit", reference="orbit_z_fixed",
        config="reference_track_orbit_eval.yaml",
        note="the first genuinely 3D maneuver; needs the post-fix rate loop and track_smooth 6",
    ),
}


def _single_drone(doc: dict, keep: int, *, drop_style: bool) -> dict:
    """The overlay with one of its two drones removed, still a valid replay.

    Structural surgery on the already-built document rather than a re-record: the episode-level
    ``drone``/``dr``/``summary``/``frames`` are a v1-reader mirror of the lead track
    (``RunRecorder.add_group_episode``), so they have to follow whichever track survives or a v1
    reader would see the wrong flight.
    """
    out = deepcopy(doc)
    ep = out["episodes"][0]
    track = deepcopy(ep["drones"][keep])
    if drop_style:
        track.pop("style", None)
    ep["drones"] = [track]
    ep["drone"] = track["drone"]
    ep["dr"] = track.get("dr")
    ep["summary"] = track["summary"]
    ep["frames"] = track["frames"]
    return out


def _write(doc: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(doc, fh)
    return path


def build_maneuver(maneuver: str, out_dir: Path) -> dict:
    """Merge, measure and plan — everything up to (but not including) the renders."""
    src = EXAMPLE_SOURCES[maneuver]
    doc, comparison = build_overlay(src.policy_replay, src.reference_json)
    plan = plan_framing(maneuver, comparison["max_separation_m"])

    # All three replays come out of the ONE overlay, which is what makes the reference clip the
    # comparison-minus-the-policy rather than a separately-framed shot of the same trajectory.
    # The reference loses its ghost styling when it stands alone: translucency is a hint about
    # which of two drones is the target, and there is no second drone in that clip.
    replays = {
        "comparison": _write(doc, out_dir / f"{maneuver}_overlay.json.gz"),
        "reference": _write(_single_drone(doc, 0, drop_style=True),
                            out_dir / f"{maneuver}_reference.json.gz"),
        "policy": _write(_single_drone(doc, 1, drop_style=False),
                         out_dir / f"{maneuver}_policy.json.gz"),
    }
    return {"source": src, "comparison": comparison, "plan": plan, "replays": replays}


def render_maneuver(maneuver: str, out_dir: Path, *, dry_run: bool) -> dict:
    """Build the three replays and render the three clips, all on one framing plan."""
    built = build_maneuver(maneuver, out_dir)
    plan, src = built["plan"], built["source"]
    print(f"\n=== {maneuver} ===")
    print(f"  policy      {src.policy_replay.relative_to(REPO_ROOT)}")
    print(f"  reference   {src.reference_json.relative_to(REPO_ROOT)}")
    print(f"  separation  {plan.separation_m:.4f} m  ->  --drone-frac {plan.drone_frac} "
          f"--scale {plan.render_scale_m} --track-smooth {plan.track_smooth}")

    clips = []
    for kind in KINDS:
        replay = built["replays"][kind]
        if dry_run:
            cmd = video_command(replay, out_dir / video_filename(maneuver, kind), framing=plan)
            print("  " + " ".join(str(c) for c in cmd))
            clips.append({"maneuver": maneuver, "kind": kind, "video": video_filename(maneuver, kind),
                          "command": [str(c) for c in cmd], "replay": str(replay)})
            continue
        clips.append(render_video(replay, out_dir, maneuver=maneuver, kind=kind, framing=plan))

    return {
        "maneuver": maneuver,
        "note": src.note,
        "policy_run": str(src.policy_replay.relative_to(REPO_ROOT)),
        "policy_config": f"configs/{src.config}",
        "reference": str(src.reference_json.relative_to(REPO_ROOT)),
        "framing_plan": plan.to_dict(),
        "tracking": {k: built["comparison"][k] for k in (
            "completed_fraction", "policy_ended", "pos_err_m_mean", "att_err_deg_mean",
            "rate_err_rps_mean", "max_separation_m", "reference_steps", "compared_steps",
            "phases_never_reached")},
        "clips": clips,
    }


def publish(master_dir: Path, manifest: dict) -> list[str]:
    """Transcode the masters to checked-in 720x720 / CRF-26 copies."""
    from imageio_ffmpeg import get_ffmpeg_exe

    PUBLISH_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for entry in manifest["maneuvers"]:
        for clip in entry["clips"]:
            src = master_dir / clip["video"]
            if not src.exists():
                print(f"[publish] skipped {clip['video']} (no master)")
                continue
            dst = PUBLISH_DIR / clip["video"]
            subprocess.run([
                get_ffmpeg_exe(), "-y", "-i", str(src),
                "-vf", f"scale={PUBLISH_SIZE}:{PUBLISH_SIZE}",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", str(PUBLISH_CRF),
                "-movflags", "+faststart", str(dst),
            ], check=True, capture_output=True)
            mb = dst.stat().st_size / 1e6
            print(f"[publish] {dst.relative_to(REPO_ROOT)}  ({mb:.2f} MB)")
            written.append(clip["video"])
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--maneuver", choices=MANEUVERS, action="append", default=None,
                    help="render only this maneuver's three clips (repeatable)")
    ap.add_argument("--out", type=Path, default=MASTER_DIR,
                    help=f"master output dir (default: {MASTER_DIR.relative_to(REPO_ROOT)})")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the argv for each clip and render nothing")
    ap.add_argument("--publish", action="store_true",
                    help=f"also write {PUBLISH_SIZE}p/CRF-{PUBLISH_CRF} copies into "
                         f"{PUBLISH_DIR.relative_to(REPO_ROOT)}/ (the checked-in ones)")
    args = ap.parse_args()

    maneuvers = args.maneuver or list(MANEUVERS)

    # runs/ is gitignored, so this is the expected state on a fresh clone. Name the producing
    # command for every missing input — a FileNotFoundError here is a dead end.
    missing = [(m, path, cmd) for m in maneuvers
               for path, cmd in EXAMPLE_SOURCES[m].missing()]
    if missing:
        print("Missing inputs (runs/ is gitignored — these are produced, not checked in):\n",
              file=sys.stderr)
        for m, path, cmd in missing:
            print(f"  {m}: {path.relative_to(REPO_ROOT)}\n      {cmd}\n", file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    entries = [render_maneuver(m, args.out, dry_run=args.dry_run) for m in maneuvers]

    manifest = {
        "generator": "scripts/render_examples.py",
        "video_args": list(BASE_VIDEO_ARGS),
        "kinds": {k: KIND_BLURBS[k] for k in KINDS},
        "publish": {"size": PUBLISH_SIZE, "crf": PUBLISH_CRF,
                    "note": f"the checked-in clips are {PUBLISH_SIZE}x{PUBLISH_SIZE} CRF-"
                            f"{PUBLISH_CRF} transcodes; the 1080x1080 masters stay in runs/"},
        "note": ("One framing plan per maneuver, derived from that maneuver's COMPARISON shot and "
                 "reused by all three of its clips. All three replays are cut from the one "
                 "overlay, so the reference clip is literally the comparison with the policy "
                 "removed: same camera path, same airframe size, same horizon."),
        "maneuvers": entries,
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nwrote {(args.out / 'manifest.json').relative_to(REPO_ROOT)}")

    if args.dry_run:
        return 0

    failed = [c for e in entries for c in e["clips"] if c.get("returncode")]
    for clip in failed:
        print(f"FAILED: {clip['video']} (rc={clip['returncode']})", file=sys.stderr)

    # The two numbers that say whether a standardized shot actually delivered. Reported per clip
    # rather than in aggregate, because the orbit is the one that fails the second without its
    # track_smooth override — which is the point of putting that in the plan.
    print("\n framing check (worst |NDC| < 0.9, apparent-size spread < 0.35):")
    bad = []
    for entry in entries:
        for clip in entry["clips"]:
            fr = clip.get("framing") or {}
            ndc, spread = fr.get("worst_ndc"), fr.get("apparent_size_spread")
            flag = ""
            if ndc is None:
                flag = "  ??  (no framing line parsed)"
            elif ndc >= 0.9 or (spread is not None and spread >= 0.35):
                flag = "  <-- OUT OF SPEC"
                bad.append(clip["video"])
            print(f"   {clip['video']:38s} |NDC| {ndc if ndc is None else f'{ndc:.2f}'}"
                  f"   spread {'n/a' if spread is None else f'{spread * 100:.0f}%'}{flag}")

    if args.publish:
        published = publish(args.out, manifest)
        manifest["published"] = published
        (PUBLISH_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
        print(f"wrote {(PUBLISH_DIR / 'manifest.json').relative_to(REPO_ROOT)}")

    return 1 if (failed or bad) else 0


if __name__ == "__main__":
    raise SystemExit(main())
