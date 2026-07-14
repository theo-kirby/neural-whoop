# Convert the whoop airframe FBX (with its authored per-part materials + image textures) into the
# Studio's self-contained GLB drone mesh. Run under Blender's bundled Python — Blender is the only
# thing on the bench Mac that reads FBX materials faithfully, and glTF export inlines everything
# (geometry + packed textures) so the frontend keeps its one-file GLTFLoader path (no FBXLoader, no
# external texture fetch).
#
#     /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
#         --python scripts/chassis_fbx_to_glb.py -- \
#         --fbx "~/Downloads/whoop-assembly 2.fbx" \
#         --tex 11.10.00=~/Downloads/battery.png \
#         --tex 11.24.43=~/Downloads/flightcontroller.png
#
# The FBX references its textures by their original authoring paths (screenshots under
# ~/Documents/captures that don't travel with the file). Each --tex SUBSTR=PATH remaps any image
# datablock whose name/path contains SUBSTR to PATH, then packs it so the GLB embeds the bytes.
# Unremapped/missing textures are skipped — the material base colors still survive. drone-model.js
# applies the CAD orientation/scale at load, so we export raw FBX axes.

import sys
from pathlib import Path

import bpy

REPO = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO / "web" / "studio" / "assets" / "whoop_chassis.glb"


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    fbx = out = None
    tex = []
    it = iter(argv)
    for a in it:
        if a == "--fbx":
            fbx = next(it)
        elif a == "--out":
            out = next(it)
        elif a == "--tex":
            substr, _, path = next(it).partition("=")
            tex.append((substr, str(Path(path).expanduser())))
    if not fbx:
        raise SystemExit("usage: --python chassis_fbx_to_glb.py -- --fbx <file.fbx> "
                         "[--out <file.glb>] [--tex SUBSTR=PATH ...]")
    return Path(fbx).expanduser(), Path(out).expanduser() if out else DEFAULT_OUT, tex


def remap_textures(tex):
    for img in bpy.data.images:
        ref = f"{img.name} {img.filepath}"
        hit = next((path for substr, path in tex if substr in ref), None)
        if hit:
            img.filepath = hit
            img.source = "FILE"
            img.reload()
            img.pack()  # embed bytes so the GLB is self-contained
            # has_data reads stale in --background right after pack; the source file is what matters.
            print(f"  texture {img.name!r} -> {hit} ({'OK' if Path(hit).exists() else 'FILE NOT FOUND'})")
        elif not img.has_data:
            print(f"  texture {img.name!r} unresolved (no --tex match) — skipped")


def main():
    fbx, out, tex = parse_args()
    out.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(fbx))
    remap_textures(tex)

    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    tris = sum(len(o.data.polygons) for o in meshes)
    mats = {m.name for o in meshes for m in o.data.materials if m}
    print(f"imported {len(meshes)} meshes, {tris} faces, {len(mats)} materials: {sorted(mats)}")

    bpy.ops.export_scene.gltf(
        filepath=str(out),
        export_format="GLB",
        export_materials="EXPORT",
        export_image_format="AUTO",
        export_yup=False,          # keep FBX/CAD axes; drone-model.js reorients at load
        use_selection=False,
        export_apply=True,
    )
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KiB)")


if __name__ == "__main__":
    main()
