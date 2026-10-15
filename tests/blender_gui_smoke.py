"""Disposable GUI session: validate projected marks and save an actual screenshot."""

import json
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector

bpy.context.preferences.view.show_splash = False
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import blender_agent_marks
from blender_agent_marks import api, viewport

OUT = ROOT / "artifacts"
OUT.mkdir(exist_ok=True)
blender_agent_marks.register()
scene = bpy.context.scene
obj = bpy.data.objects["Cube"]
obj.name = "Surface annotation demo"
obj.data.calc_loop_triangles()
notes = ["Round this edge", "Keep this panel flat", "Add a shallow groove"]
for i, point in enumerate(((-0.6, -0.5, 1), (0.35, 0.15, 1), (-0.45, 0.7, 1))):
    for tri in obj.data.loop_triangles:
        if tri.normal.z < 0.9:
            continue
        try:
            api.create(scene, obj.name, tri.index, point, notes[i])
            break
        except api.MarkError:
            continue
    else:
        raise AssertionError("No demo triangle")

for view in viewport.viewports(scene):
    space = view[3]
    space.shading.type = "SOLID"
    space.shading.show_xray = False
    space.overlay.show_floor = False
    space.overlay.show_axis_x = False
    space.overlay.show_axis_y = False
    space.region_3d.view_rotation = Quaternion((1, 0, 0, 0))
    space.region_3d.view_distance = 7
    space.region_3d.view_location = (0, 0, 0)
    space.region_3d.view_perspective = "ORTHO"
    space.show_region_ui = True
    view[1].tag_redraw()

checks = []


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)


def validate():
    try:
        view = next(viewport.viewports(scene))
        for region in view[1].regions:
            if region.type == "UI":
                region.active_panel_category = "FacetCue for Blender"
        identifier = viewport.viewport_id(view)
        response = api.dispatch("list_marks", {"viewport_id": identifier})
        one_call = api.dispatch("get_surface_annotations")
        check(
            "one_call_auto_selects_viewport",
            one_call["ok"]
            and one_call["total"] == 3
            and all(m["viewport"]["state"] == "VISIBLE" for m in one_call["annotations"]),
        )
        check(
            "three_visible_orthographic_marks",
            response["ok"] and all(m["viewport"]["state"] == "VISIBLE" for m in response["data"]),
        )
        mark = api.marks(scene)[0]
        visible = api.serialize(scene, mark, view)["viewport"]
        check("overlay_visible", visible["overlay_drawn"])
        bpy.context.window_manager.asm_show_overlay = False
        state = api.serialize(scene, mark, view)["viewport"]
        check(
            "toggle_only_hides_overlay", state["state"] == "VISIBLE" and not state["overlay_drawn"]
        )
        bpy.context.window_manager.asm_show_overlay = True
        obj.hide_set(True)
        check(
            "object_hidden",
            api.serialize(scene, mark, view)["viewport"]["state"] == "OBJECT_HIDDEN",
        )
        obj.hide_set(False)
        blocker_mesh = bpy.data.meshes.new("Blocker")
        blocker_mesh.from_pydata(
            [(-2, -2, 2), (2, -2, 2), (2, 2, 2), (-2, 2, 2)], [], [(0, 1, 2, 3)]
        )
        blocker = bpy.data.objects.new("Blocker", blocker_mesh)
        scene.collection.objects.link(blocker)
        bpy.context.view_layer.update()
        check(
            "occluded_surface", api.serialize(scene, mark, view)["viewport"]["state"] == "OCCLUDED"
        )
        blocker.hide_set(True)
        check(
            "hidden_blocker_ignored",
            api.serialize(scene, mark, view)["viewport"]["state"] == "VISIBLE",
        )
        bpy.data.objects.remove(blocker, do_unlink=True)
        view[3].shading.show_xray = True
        check(
            "xray_projection_visible",
            api.serialize(scene, mark, view)["viewport"]["state"] == "XRAY",
        )
        view[3].shading.show_xray = False
        screen = visible["screen_px"]
        clicked = viewport.create_at_pixel(scene, view, *screen, "Click ray validation")
        check(
            "screen_ray_roundtrip",
            (
                Vector(clicked["resolved"]["world_position"])
                - Vector(api.resolve(scene, mark)["world_position"])
            ).length
            < 1e-4,
        )
        api.document(scene).asm_marks.remove(len(api.marks(scene)) - 1)
        api.document(scene).asm_active_index = 0
        (OUT / "viewport_response.json").write_text(
            json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "demo.blend"))
        view[1].tag_redraw()
        view[3].region_3d.view_perspective = "PERSP"
        bpy.app.timers.register(validate_perspective, first_interval=2)
    except Exception:
        (OUT / "gui_test_error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        bpy.ops.wm.quit_blender()
    return None


def validate_perspective():
    try:
        view = next(viewport.viewports(scene))
        mark = api.marks(scene)[0]
        check(
            "perspective_visible",
            api.serialize(scene, mark, view)["viewport"]["state"] == "VISIBLE",
        )
        obj.location.x = 100
        bpy.context.view_layer.update()
        check("offscreen", api.serialize(scene, mark, view)["viewport"]["state"] == "OFFSCREEN")
        obj.location.x = 0
        obj.location.z = 20
        bpy.context.view_layer.update()
        check("behind_view", api.serialize(scene, mark, view)["viewport"]["state"] == "BEHIND_VIEW")
        obj.location.z = 0
        bpy.context.view_layer.update()
        view[1].tag_redraw()
        bpy.app.timers.register(capture, first_interval=2)
    except Exception:
        (OUT / "gui_test_error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        bpy.ops.wm.quit_blender()
    return None


def capture():
    try:
        bpy.ops.screen.screenshot(filepath=str(OUT / "viewport_preview.png"))
        checks.append("viewport_screenshot_saved")
        (OUT / "gui_test_report.json").write_text(
            json.dumps(
                {"blender": bpy.app.version_string, "checks_passed": len(checks), "checks": checks},
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        (OUT / "gui_test_error.txt").write_text(traceback.format_exc(), encoding="utf-8")
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(validate, first_interval=3)
