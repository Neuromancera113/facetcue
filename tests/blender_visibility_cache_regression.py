"""Isolated GUI checks for accelerated queries and redraw-bounded visibility caches."""

import json
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import blender_agent_marks
from blender_agent_marks import api, spatial, ui, ux, viewport

OUT = ROOT / "artifacts"
blender_agent_marks.register()
bpy.context.preferences.view.show_splash = False
scene = bpy.context.scene
cube = scene.objects["Cube"]
cube.data.calc_loop_triangles()
for triangle in cube.data.loop_triangles:
    if triangle.normal.z > 0.9:
        try:
            record = api.create(scene, cube.name, triangle.index, (0.2, 0.1, 1), "Cache regression")
            break
        except api.MarkError:
            pass
mark = api.get_mark(scene, record["id"])
view = next(viewport.viewports(scene))
view.space.shading.type = "SOLID"
view.space.region_3d.view_rotation = Quaternion((1, 0, 0, 0))
view.space.region_3d.view_location = (0, 0, 0)
view.space.region_3d.view_distance = 7
view.space.region_3d.view_perspective = "ORTHO"
checks = []


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)


def state():
    # A new draw batch must observe display flags even before a depsgraph event.
    viewport.begin_query_batch(ux.GEOMETRY_CACHE)
    cached = api.serialize(scene, mark, view, ux.GEOMETRY_CACHE)["viewport"]
    fresh = api.serialize(scene, mark, view)["viewport"]
    check("fresh_and_cached_visibility_agree", cached == fresh)
    return cached


def pick():
    return viewport.pick_surface(scene, view, *state()["screen_px"])


def blocker(name, center):
    mesh = cube.data.copy()
    obj = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(obj)
    obj.location = center
    obj.scale = (0.6, 0.6, 0.2)
    bpy.context.view_layer.update()
    return obj


def compare_paths():
    point = Vector(api.resolve(scene, mark)["world_position"])
    info = state()
    origin, _ = viewport.ray_from_pixel(view, *info["screen_px"])
    direction = (point - origin).normalized()
    limit = (point - origin).length + 0.001
    fast = viewport.nearest_hit(scene, view, origin, direction, limit, {})
    slow = viewport.nearest_hit_conservative(scene, view, origin, direction, limit)
    check(
        "accelerated_and_conservative_agree",
        fast is not None
        and slow is not None
        and fast.obj == slow.obj
        and fast.is_instance == slow.is_instance
        and fast.reason == slow.reason
        and (fast.point_world - slow.point_world).length < 1e-4,
    )


def validate():
    try:
        check("ordinary_scene_has_spatial_acceleration", spatial.get_index(view).supported)
        check("front_surface_visible", state()["state"] == "VISIBLE")
        check(
            "pixel_pick_preserves_local_position", (pick()[2] - Vector((0.2, 0.1, 1))).length < 1e-4
        )
        compare_paths()
        bpy.context.view_layer.objects.active = cube
        cube.select_set(True)
        with bpy.context.temp_override(window=view.window, area=view.area, region=view.region):
            bpy.ops.object.mode_set(mode="EDIT")
        check("edit_mode_not_hidden_by_warm_cache", state()["state"] == "ANCHOR_INVALID")
        with bpy.context.temp_override(window=view.window, area=view.area, region=view.region):
            bpy.ops.object.mode_set(mode="OBJECT")
        check("leaving_edit_mode_refreshes_cache", state()["state"] == "VISIBLE")
        cached_topology = api.geometry(cube, ux.GEOMETRY_CACHE)
        viewport.begin_query_batch(ux.GEOMETRY_CACHE)
        check(
            "redraw_keeps_topology_cache",
            ux.GEOMETRY_CACHE[cube.data.as_pointer()] is cached_topology,
        )

        front = blocker("Foreground", (0, 0, 2))
        check("new_geometry_occludes", state()["state"] == "OCCLUDED")
        compare_paths()
        front.hide_set(True)
        check("hide_without_manual_cache_clear", state()["state"] == "VISIBLE")
        front.hide_set(False)
        check("unhide_without_manual_cache_clear", state()["state"] == "OCCLUDED")
        front.location.x = 5
        bpy.context.view_layer.update()
        check("transform_invalidates_visibility", state()["state"] == "VISIBLE")

        special = blocker("Display changes", (0, 0, -3))
        check("ordinary_behind_surface", state()["state"] == "VISIBLE")
        special.show_in_front = True
        check("in_front_flag_without_transform", state()["reason"] == "in_front_geometry")
        special.show_in_front = False
        check("clear_in_front_flag_without_transform", state()["state"] == "VISIBLE")
        special.location.z = 2
        bpy.context.view_layer.update()
        special.display_type = "WIRE"
        check("wire_bounds_remain_conservative", state()["reason"] == "wire_or_bounds_geometry")
        special.display_type = "BOUNDS"
        check("bounds_display_remains_conservative", state()["reason"] == "wire_or_bounds_geometry")
        special.display_type = "SOLID"
        check("restore_solid_display_occludes", state()["state"] == "OCCLUDED")
        bpy.data.objects.remove(special, do_unlink=True)
        bpy.context.view_layer.update()
        check("deleted_blocker_not_cached", state()["state"] == "VISIBLE")

        # Curve-generated evaluated meshes must remain valid across iteration.
        curve_data = bpy.data.curves.new("Filled curve", "CURVE")
        curve_data.dimensions = "2D"
        curve_data.fill_mode = "BOTH"
        spline = curve_data.splines.new("POLY")
        spline.points.add(3)
        for bp, co in zip(
            spline.points, ((-1, -1, 0, 1), (1, -1, 0, 1), (1, 1, 0, 1), (-1, 1, 0, 1))
        ):
            bp.co = co
        spline.use_cyclic_u = True
        curve = bpy.data.objects.new("Curve occluder", curve_data)
        scene.collection.objects.link(curve)
        curve.location.z = 2
        bpy.context.view_layer.update()
        check("generated_curve_has_spatial_acceleration", spatial.get_index(view).supported)
        check("curve_generated_mesh_occludes", state()["state"] == "OCCLUDED")
        compare_paths()
        try:
            pick()
            raise AssertionError("Picked through curve")
        except api.MarkError as exc:
            check("curve_is_not_anchored_as_original_mesh", exc.code == "NON_MESH_TARGET")
        curve.hide_set(True)
        bpy.context.view_layer.update()
        check("hidden_curve_cache_invalidation", state()["state"] == "VISIBLE")

        # An outside-local-view blocker cannot hide the isolated target.
        front.location.x = 0
        bpy.context.view_layer.update()
        bpy.ops.object.select_all(action="DESELECT")
        cube.select_set(True)
        bpy.context.view_layer.objects.active = cube
        with bpy.context.temp_override(window=view.window, area=view.area, region=view.region):
            bpy.ops.view3d.localview(frame_selected=False)
        check("local_view_keeps_spatial_acceleration", spatial.get_index(view).supported)
        check("outside_local_view_does_not_occlude", state()["state"] == "VISIBLE")
        check("local_view_pixel_pick", pick()[0] == cube)
        with bpy.context.temp_override(window=view.window, area=view.area, region=view.region):
            bpy.ops.view3d.localview(frame_selected=False)
        check("leaving_local_view_restores_blocker", state()["state"] == "OCCLUDED")
        front.hide_set(True)
        bpy.context.view_layer.update()

        # A scene membership cache must never keep an unlinked anchor valid.
        collections = list(cube.users_collection)
        other = bpy.data.scenes.new("Different scene")
        other.collection.objects.link(cube)
        for collection in collections:
            collection.objects.unlink(cube)
        bpy.context.view_layer.update()
        check("unlink_invalidates_membership_cache", state()["state"] == "ANCHOR_INVALID")
        for collection in collections:
            collection.objects.link(cube)
        bpy.context.view_layer.update()
        check("relink_restores_original_anchor", state()["state"] == "VISIBLE")

        # Location must track a changed original transform, including mirrored scale.
        cube.scale = (-1.7, 0.7, 1.3)
        cube.location = (0.1, -0.2, -0.1)
        bpy.context.view_layer.update()
        compare_paths()
        check("nonuniform_mirrored_transform_visible", state()["state"] == "VISIBLE")
        check("mirrored_transform_pixel_pick", (pick()[2] - Vector((0.2, 0.1, 1))).length < 1e-4)
        view.space.shading.show_xray = True
        front.hide_set(False)
        bpy.context.view_layer.update()
        xray = state()
        check(
            "xray_retains_occlusion_classification",
            xray["state"] == "XRAY" and xray["surface_visibility"] == "OCCLUDED",
        )
        check(
            "xray_retains_dimmed_opacity", xray["display_opacity"] == viewport.XRAY_OCCLUDED_OPACITY
        )
        view.space.shading.show_xray = False

        before = api.serialize(scene, mark)
        manager = bpy.context.window_manager
        manager.asm_show_overlay = False
        manager.asm_filter = "ARCHIVED"
        view.space.overlay.show_overlays = False
        agent = api.dispatch("get_surface_annotations")
        check(
            "mcp_independent_of_overlays_and_filters",
            agent["ok"]
            and agent["total"] == 1
            and agent["annotations"][0]["resolved"]["state"] == "VALID",
        )
        manager.asm_show_overlay = True
        manager.asm_filter = "ALL"
        view.space.overlay.show_overlays = True
        with bpy.context.temp_override(window=view.window, area=view.area, region=view.region):
            list(ui.drawn_marks(bpy.context))
        check("queries_never_change_annotation_metadata", before == api.serialize(scene, mark))
        (OUT / "visibility_cache_report.json").write_text(
            json.dumps(
                {"blender": bpy.app.version_string, "checks_passed": len(checks), "checks": checks},
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        (OUT / "visibility_cache_error.txt").write_text(
            traceback.format_exc() + "\n" + json.dumps(checks), encoding="utf-8"
        )
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(validate, first_interval=2)
