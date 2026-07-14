# Convert the whoop airframe FBX (with its authored per-part materials) into the Studio's
# self-contained GLB drone mesh. Run under Blender's bundled Python — Blender is the only thing on
# the bench Mac that reads FBX materials faithfully, and glTF export inlines everything so the
# frontend keeps its one-file GLTFLoader path (no FBXLoader, no external texture fetch).
#
#     /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
#         --python scripts/chassis_fbx_to_glb.py -- \
#         --fbx ~/Downloads/whoop-assembly.fbx
#
# Missing external textures (e.g. a stale screenshot ref) are skipped — the material base colors
# survive. drone-model.js applies the CAD orientation/scale at load, so we export raw FBX axes.

import sys
from pathlib import Path

import bpy

REPO = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO / "web" / "studio" / "assets" / "whoop_chassis.glb"


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    fbx = out = None
    it = iter(argv)
    for a in it:
        if a == "--fbx":
            fbx = next(it)
        elif a == "--out":
            out = next(it)
    if not fbx:
        raise SystemExit("usage: --python chassis_fbx_to_glb.py -- --fbx <file.fbx> [--out <file.glb>]")
    return Path(fbx).expanduser(), Path(out).expanduser() if out else DEFAULT_OUT


def main():
    fbx, out = parse_args()
    out.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(fbx))

    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    tris = sum(len(o.data.polygons) for o in meshes)
    mats = {m.name for o in meshes for m in o.data.materials if m}
    print(f"imported {len(meshes)} meshes, {tris} faces, {len(mats)} materials: {sorted(mats)}")

    bpy.ops.export_scene.gltf(
        filepath=str(out),
        export_format="GLB",
        export_materials="EXPORT",
        export_yup=False,          # keep FBX/CAD axes; drone-model.js reorients at load
        use_selection=False,
        export_apply=True,
    )
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KiB)")


if __name__ == "__main__":
    main()
