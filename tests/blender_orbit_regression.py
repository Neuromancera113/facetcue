"""Isolated GUI regression for rotating/panning a view with surface annotations."""

import json
import math
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import blender_agent_marks
from blender_agent_marks import api, ux, viewport

OUT = ROOT / "artifacts"
blender_agent_marks.register()
bpy.context.preferences.view.show_splash = False
scene = bpy.context.scene
cube = scene.objects["Cube"]
point_local = Vector((-0.5243778228759766, 1.0, 0.678382396697998))
cube.data.calc_loop_triangles()
record = api.create(scene, cube.name, 10, point_local, "Orbit regression")
mark = api.get_mark(scene, record["id"])
checks = []
samples = []


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)


def inspect_pose(view, name, expected, *, pick=False):
    # The UI reuses this cache; the agent reads with fresh data. Both must agree.
    view.space.region_3d.update()
    fresh = api.serialize(scene, mark, view)["viewport"]
    cached = api.serialize(scene, mark, view, ux.GEOMETRY_CACHE)["viewport"]
    samples.append({"name": name, "expected": expected, "fresh": fresh, "cached": cached})
    check(name + ": visibility", fresh["state"] == cached["state"] == expected)
    check(name + ": overlay", fresh["overlay_drawn"] == (expected == "VISIBLE"))
    if pick:
        obj, _, picked_local, _ = viewport.pick_surface(scene, view, *fresh["screen_px"])
        check(
            name + ": pixel round trip", obj == cube and (picked_local - point_local).length < 1e-4
        )


def validate():
    try:
        view = next(viewport.viewports(scene))
        space = view.space
        region_3d = space.region_3d
        space.shading.type = "SOLID"
        space.shading.show_xray = False
        space.clip_start = 0.01
        space.clip_end = 1000
        region_3d.view_perspective = "PERSP"
        # Observed failing pose: old unprojection missed the anchor by ~0.0013.
        region_3d.view_rotation = Quaternion(
            (0.416960209608078, 0.37337526679039, 0.552819013595581, 0.617354154586792)
        )
        region_3d.view_location = (-0.020693248137831688, -0.04602546989917755, 0.00066943076672)
        region_3d.view_distance = 18.38804817199707
        inspect_pose(view, "reported perspective pose", "VISIBLE", pick=True)

        for mode in ("PERSP", "ORTHO"):
            region_3d.view_perspective = mode
            for far_clip in (1000, 100000):
                space.clip_end = far_clip
                for angle_degrees in range(-80, 81, 4):
                    angle = math.radians(angle_degrees)
                    eye_direction = Vector((math.sin(angle), math.cos(angle), 0.12))
                    region_3d.view_rotation = eye_direction.to_track_quat("Z", "Y")
                    region_3d.view_distance = 18 + 2 * math.sin(angle)
                    region_3d.view_location = (0.1 * math.sin(angle), 0, 0.1 * math.cos(angle))
                    inspect_pose(
                        view,
                        f"{mode} far={far_clip} angle={angle_degrees}",
                        "VISIBLE",
                        pick=mode == "PERSP",
                    )
            space.clip_end = 1000
            for angle_degrees in (110, 140, 180, 220, 250):
                angle = math.radians(angle_degrees)
                region_3d.view_rotation = Vector(
                    (math.sin(angle), math.cos(angle), 0.12)
                ).to_track_quat("Z", "Y")
                inspect_pose(view, f"{mode} back angle={angle_degrees}", "OCCLUDED")

        # A separate foreground surface must still hide the mark after the fix.
        region_3d.view_perspective = "PERSP"
        region_3d.view_rotation = Vector((0, 1, 0)).to_track_quat("Z", "Y")
        region_3d.view_location = (0, 0, 0)
        blocker_mesh = bpy.data.meshes.new("Occluder")
        blocker_mesh.from_pydata(
            [(-2, 2, -2), (2, 2, -2), (2, 2, 2), (-2, 2, 2)], [], [(0, 1, 2, 3)]
        )
        blocker = bpy.data.objects.new("Occluder", blocker_mesh)
        scene.collection.objects.link(blocker)
        bpy.context.view_layer.update()
        inspect_pose(view, "foreground blocker", "OCCLUDED")
        blocker.hide_set(True)
        bpy.context.view_layer.update()
        inspect_pose(view, "blocker removed", "VISIBLE", pick=True)

        # Refresh only this stateless calculation module; user metadata, RNA UI
        # registrations and Undo history do not need a full add-on reload.
        import importlib

        before = api.serialize(scene, mark)
        importlib.reload(viewport)
        check("viewport refresh preserves annotation", before == api.serialize(scene, mark))
        inspect_pose(view, "refreshed viewport module", "VISIBLE", pick=True)
        (OUT / "orbit_test_report.json").write_text(
            json.dumps(
                {"blender": bpy.app.version_string, "checks_passed": len(checks), "checks": checks},
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        (OUT / "orbit_test_error.txt").write_text(traceback.format_exc(), encoding="utf-8")
    finally:
        (OUT / "orbit_samples.json").write_text(json.dumps(samples, indent=2), encoding="utf-8")
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(validate, first_interval=2)
