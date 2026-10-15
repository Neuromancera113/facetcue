"""Regression for mesh annotations in scenes with curves, text and instances.

Run in a separate factory-startup GUI Blender. No user scene is opened or edited.
"""

import json
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Quaternion

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import blender_agent_marks
from blender_agent_marks import api, ux, viewport

OUT = ROOT / "artifacts"
for name in ("mixed_scene_report.json", "mixed_scene_error.txt"):
    (OUT / name).unlink(missing_ok=True)
blender_agent_marks.register()
bpy.context.preferences.view.show_splash = False
scene = bpy.context.scene
cube = bpy.data.objects["Cube"]
cube.data.calc_loop_triangles()
for tri in cube.data.loop_triangles:
    if tri.normal.z > 0.9:
        try:
            record = api.create(scene, cube.name, tri.index, (0, 0, 1), "表面标记")
            break
        except api.MarkError:
            pass
mark = api.get_mark(scene, record["id"])
view = next(viewport.viewports(scene))
view[3].region_3d.view_rotation = Quaternion((1, 0, 0, 0))
view[3].region_3d.view_location = (0, 0, 0)
view[3].region_3d.view_distance = 7
view[3].region_3d.view_perspective = "ORTHO"
view[3].shading.type = "SOLID"

curve_data = bpy.data.curves.new("Curve geometry", "CURVE")
curve_data.dimensions = "2D"
curve_data.fill_mode = "BOTH"
curve_data.extrude = 0.05
spline = curve_data.splines.new("POLY")
spline.points.add(3)
for p, co in zip(
    spline.points, ((-0.7, -0.7, 0, 1), (0.7, -0.7, 0, 1), (0.7, 0.7, 0, 1), (-0.7, 0.7, 0, 1))
):
    p.co = co
spline.use_cyclic_u = True
curve = bpy.data.objects.new("Curved railing", curve_data)
scene.collection.objects.link(curve)
curve.location = (10, 0, 2)
font_data = bpy.data.curves.new("Letter geometry", "FONT")
font_data.body = "I"
font_data.size = 3
font_data.align_x = "CENTER"
font_data.align_y = "CENTER"
font = bpy.data.objects.new("Text sign", font_data)
scene.collection.objects.link(font)
font.location = (10, 0, 2)
source_collection = bpy.data.collections.new("Instance source not directly in scene")
source = bpy.data.objects.new("Instance source mesh", cube.data.copy())
source_collection.objects.link(source)
instancer = bpy.data.objects.new("Visible collection instance", None)
instancer.instance_type = "COLLECTION"
instancer.instance_collection = source_collection
scene.collection.objects.link(instancer)
instancer.location = (10, 0, 2)
instancer.scale = (0.4, 0.4, 0.4)
special = bpy.data.objects.new("Special-display mesh", cube.data.copy())
scene.collection.objects.link(special)
special.location = (10, 0, 0)
special.display_type = "WIRE"
bpy.context.view_layer.update()
checks = []


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)


def state():
    return api.serialize(scene, mark, view, ux.GEOMETRY_CACHE)["viewport"]


def move(obj, location):
    obj.location = location
    bpy.context.view_layer.update()


def expect_pick_error(name, code, x, y):
    try:
        viewport.pick_surface(scene, view, x, y)
    except api.MarkError as exc:
        check(name, exc.code == code)
        return str(exc)
    raise AssertionError(name + ": unexpected pick success")


def validate():
    try:
        check("mixed_scene_not_globally_rejected", viewport.support_reason(scene, view) is None)
        check("off_ray_curves_text_instances_allow_visibility", state()["state"] == "VISIBLE")
        x, y = state()["screen_px"]
        picked = viewport.pick_surface(scene, view, x, y)
        check("mesh_pick_in_mixed_scene", picked[0] == cube)
        count = len(api.marks(scene))
        created = viewport.create_at_pixel(scene, view, x, y, "混合场景放点")
        check(
            "create_mesh_mark_in_mixed_scene",
            created["resolved"]["state"] == "VALID" and len(api.marks(scene)) == count + 1,
        )
        move(curve, (0, 0, 2))
        check("curve_blocks_mark_and_invalidates_cache", state()["state"] == "OCCLUDED")
        detail = expect_pick_error("curve_not_picked_through", "NON_MESH_TARGET", x, y)
        check("curve_error_identifies_object", curve.name in detail)
        curve.hide_set(True)
        bpy.context.view_layer.update()
        check("hidden_curve_no_longer_occludes", state()["state"] == "VISIBLE")
        move(curve, (10, 0, 2))
        curve.hide_set(False)
        bpy.context.view_layer.update()
        # Generated geometry has different lifetime rules from original objects.
        for _ in range(3):
            check(
                "generated_mesh_iterator_stable_" + str(_),
                viewport.pick_surface(scene, view, x, y)[0] == cube,
            )
        move(font, (0, 0, 2))
        check("font_blocks_mark", state()["state"] == "OCCLUDED")
        expect_pick_error("font_not_picked_through", "NON_MESH_TARGET", x, y)
        move(font, (10, 0, 2))
        move(instancer, (0, 0, 2))
        check("real_instance_blocks_mark", state()["state"] == "OCCLUDED")
        expect_pick_error(
            "instance_anchor_not_silently_attached_to_source", "INSTANCE_TARGET", x, y
        )
        instancer.hide_set(True)
        bpy.context.view_layer.update()
        check("hidden_instancer_no_longer_occludes", state()["state"] == "VISIBLE")
        move(instancer, (10, 0, 2))
        move(special, (0, 0, 3))
        check(
            "wire_crossing_ray_is_explicitly_unknown",
            state()["state"] == "UNKNOWN" and state()["reason"] == "wire_or_bounds_geometry",
        )
        expect_pick_error("wire_display_specific_error", "UNSUPPORTED_TARGET", x, y)
        special.display_type = "SOLID"
        special.show_in_front = True
        move(special, (0, 0, -3))
        check(
            "in_front_behind_surface_not_ignored",
            state()["state"] == "UNKNOWN" and state()["reason"] == "in_front_geometry",
        )
        move(special, (10, 0, -3))
        check("off_ray_special_display_does_not_block", state()["state"] == "VISIBLE")
        check("scene_has_only_confirmed_marks", len(api.marks(scene)) == count + 1)
        view[3].shading.show_xray = True
        check(
            "xray_allows_front_surface_placement",
            viewport.pick_surface(scene, view, x, y)[0] == cube,
        )
        check(
            "xray_uses_projection",
            state()["state"] == "XRAY" and state()["overlay_drawn"],
        )
        view[3].shading.show_xray = False
        check(
            "mixed_scene_agent_read", api.dispatch("get_surface_annotations")["total"] == count + 1
        )
        (OUT / "mixed_scene_report.json").write_text(
            json.dumps(
                {"blender": bpy.app.version_string, "checks_passed": len(checks), "checks": checks},
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        (OUT / "mixed_scene_error.txt").write_text(
            traceback.format_exc() + "\n" + json.dumps(checks), encoding="utf-8"
        )
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(validate, first_interval=3)
