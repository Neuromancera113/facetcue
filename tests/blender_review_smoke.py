"""Real input, review badges and X-Ray behavior in an isolated Blender GUI."""

import json
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import blender_agent_marks
from blender_agent_marks import api, editor, floating, review, shortcuts, ui, ux, viewport

OUT = ROOT / "artifacts"
blender_agent_marks.register()
bpy.context.preferences.view.show_splash = False
scene = bpy.context.scene
cube = scene.objects["Cube"]
checks = []


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)


def add(point, note):
    cube.data.calc_loop_triangles()
    for triangle in cube.data.loop_triangles:
        try:
            return api.create(scene, cube.name, triangle.index, point, note)
        except api.MarkError:
            continue
    raise AssertionError("No matching triangle")


first = add((-0.6, -0.5, 1), "Round this corner")
second = add((0.5, 0.4, -1), "Inspect the hidden side")
third = add((0.5, -0.5, 1), "Untouched request")
first_id, second_id = first["id"], second["id"]
view = next(viewport.viewports(scene))
window, area, region, space = view
space.shading.type = "SOLID"
space.region_3d.view_rotation = Quaternion((1, 0, 0, 0))
space.region_3d.view_distance = 7
space.region_3d.view_perspective = "PERSP"
space.show_region_ui = True
api.document(scene).asm_active_index = 0


def key(event_type, **modifiers):
    for value in ("PRESS", "RELEASE"):
        if value == "RELEASE":
            modifiers.pop("unicode", None)
        window.event_simulate(
            type=event_type,
            value=value,
            x=region.x + 120,
            y=region.y + min(80, region.height // 2),
            **modifiers,
        )


def shortcut(event_type):
    key(event_type, ctrl=True, alt=True, shift=True)


def type_text(value):
    for char in value:
        key("A", unicode=char)


def call(operator, **arguments):
    with bpy.context.temp_override(window=window, area=area, region=region):
        return operator("EXEC_DEFAULT", True, **arguments)


def request(record):
    return {
        "scene_name": scene.name,
        "marker_id": record["id"],
        "expected_revision": record["revision"],
        "summary": "Completed requested model change",
    }


def steps():
    for item in area.regions:
        if item.type == "UI":
            item.active_panel_category = "FacetCue for Blender"
    check("default_shortcuts_have_no_blender_conflict", not shortcuts.CONFLICTS)
    shortcut("A")
    yield 0.2
    shortcut("M")
    yield 0.2
    check(
        "toggle_off_cancels_placement",
        not ui._active_placements and not bpy.context.window_manager.asm_show_overlay,
    )
    shortcut("M")
    yield 0.2
    check("unprocessed_marker_has_no_badge", first["status_badge"] is None)
    base_colors = [tuple(mark.color) for mark in api.marks(scene)]
    check("initial_marker_colors_distinct", len(set(base_colors)) == 3)
    cube.location.x = 0.1
    bpy.context.view_layer.update()
    model_after_agent = cube.matrix_world.copy()
    batch = [request(first), request(second)]
    submitted = review.submit_changes(batch)
    check(
        "agent_submission_sets_review_state",
        all(mark["status"] == "MODIFIED" for mark in submitted["annotations"]),
    )
    check(
        "review_badge_does_not_replace_marker_colors",
        [tuple(mark.color) for mark in api.marks(scene)] == base_colors,
    )
    check(
        "blue_status_badge_is_serialized",
        all(mark["status_badge"]["color"][2] == 1.0 for mark in submitted["annotations"]),
    )
    check("agent_retry_is_idempotent", review.submit_changes(batch) == submitted)
    bad_batch = [request(third), {**request(first), "expected_revision": 99}]
    try:
        review.submit_changes(bad_batch)
    except api.MarkError as exc:
        check(
            "batch_conflict_has_no_partial_status_write",
            exc.code == "REVISION_CONFLICT" and api.get_mark(scene, third["id"]).status == "OPEN",
        )
    else:
        raise AssertionError("Stale batch was accepted")

    shortcut("RET")
    yield 0.5
    check("approval_shortcut", api.get_mark(scene, first_id).status == "RESOLVED")
    check(
        "approval_removes_badge",
        api.serialize(scene, api.get_mark(scene, first_id))["status_badge"] is None,
    )
    shortcut("Z")
    yield 0.5
    check(
        "withdraw_restores_review_without_model_undo",
        api.get_mark(scene, first_id).status == "MODIFIED"
        and cube.matrix_world == model_after_agent,
    )
    shortcut("BACK_SPACE")
    yield 0.5
    check(
        "reject_uses_compact_input",
        area.type == "VIEW_3D" and len(bpy.context.window_manager.windows) == 1,
    )
    key("A", ctrl=True)
    type_text("Use a smaller radius")
    yield 0.3
    check(
        "reject_draft_does_not_publish_before_enter",
        api.get_mark(scene, first_id).note == first["note"],
    )
    key("RET")
    yield 0.5
    mark = api.get_mark(scene, first_id)
    check(
        "one_enter_rejects_and_exits",
        area.type == "VIEW_3D"
        and mark.status == "CHANGES_REQUESTED"
        and mark.note == "Use a smaller radius",
    )
    shortcut("Z")
    yield 0.5
    mark = api.get_mark(scene, first_id)
    check(
        "withdraw_restores_original_note_status_and_color",
        mark.note == first["note"]
        and mark.status == "MODIFIED"
        and tuple(mark.color) == base_colors[0],
    )
    check("withdraw_leaves_model_change_intact", cube.matrix_world == model_after_agent)
    shortcut("BACK_SPACE")
    yield 0.3
    type_text("cancelled")
    key("ESC")
    yield 0.3
    check(
        "reject_cancel_does_not_change_status_or_note",
        area.type == "VIEW_3D"
        and api.get_mark(scene, first_id).note == first["note"]
        and api.get_mark(scene, first_id).status == "MODIFIED",
    )
    selection = [obj.name for obj in bpy.context.selected_objects]
    shortcut("RIGHT_ARROW")
    yield 0.3
    check("next_shortcut_selects_next_marker", ux.active_mark(scene).marker_id == second_id)
    check(
        "focus_uses_annotation_as_orbit_pivot",
        (
            space.region_3d.view_location
            - Vector(api.resolve(scene, ux.active_mark(scene))["world_position"])
        ).length
        < 1e-5,
    )
    check(
        "focus_uses_close_distance_and_preserves_selection",
        space.region_3d.view_distance < 2
        and [obj.name for obj in bpy.context.selected_objects] == selection,
    )
    shortcut("LEFT_ARROW")
    yield 0.3
    check("previous_shortcut_selects_previous_marker", ux.active_mark(scene).marker_id == first_id)
    shortcut("M")
    yield 0.3
    check(
        "toggle_off_keeps_agent_data",
        not bpy.context.window_manager.asm_show_overlay,
    )
    check("agent_reads_while_ui_is_disabled", api.get_surface_annotations()["total"] == 3)
    shortcut("M")
    yield 0.3
    check("toggle_on_restores_overlay", bpy.context.window_manager.asm_show_overlay)

    space.region_3d.view_rotation = Quaternion((1, 0, 0, 0))
    space.region_3d.view_location = (0, 0, 0)
    space.region_3d.view_distance = 7
    space.region_3d.update()
    hidden = api.get_mark(scene, second_id)
    check(
        "normal_view_hides_back_marker",
        api.serialize(scene, hidden, view)["viewport"]["state"] == "OCCLUDED",
    )
    key("Z", alt=True)
    yield 0.5
    states = [api.serialize(scene, mark, view)["viewport"] for mark in api.marks(scene)]
    check(
        "alt_z_shows_all_projected_markers",
        all(state["state"] == "XRAY" and state["overlay_drawn"] for state in states),
    )
    check("xray_notes_default_collapsed", not bpy.context.window_manager.asm_expand_xray_note)
    check(
        "xray_only_occluded_markers_are_60_percent_transparent",
        [state["surface_visibility"] for state in states] == ["VISIBLE", "OCCLUDED", "VISIBLE"]
        and [state["display_opacity"] for state in states] == [1.0, 0.4, 1.0],
    )
    with bpy.context.temp_override(window=window, area=area, region=region):
        drawn = list(ui.drawn_marks(bpy.context))
    check(
        "badges_share_parent_visibility",
        len(drawn) == 3 and sum(record["status_badge"] is not None for _, record in drawn) == 2,
    )
    bpy.ops.screen.screenshot(filepath=str(OUT / "review_xray_preview.png"))
    key("Z", alt=True)
    yield 0.5
    check(
        "leaving_xray_restores_occlusion",
        api.serialize(scene, hidden, view)["viewport"]["state"] == "OCCLUDED",
    )

    call(bpy.ops.asm.review, action="APPROVE")
    mark = api.get_mark(scene, first_id)
    api.update(scene, mark.marker_id, mark.revision, note="Newer user request")
    check(
        "withdraw_refuses_to_overwrite_newer_edits",
        call(bpy.ops.asm.review, action="WITHDRAW") == {"CANCELLED"}
        and mark.note == "Newer user request",
    )
    map_ = bpy.context.window_manager.keyconfigs.addon.keymaps.new(
        name="Window", space_type="EMPTY"
    )
    item = map_.keymap_items.new("wm.call_menu", "A", "PRESS", ctrl=True, alt=True, shift=True)
    check(
        "custom_key_conflict_detected", bool(shortcuts.conflicts(bpy.context.window_manager, "A"))
    )
    map_.keymap_items.remove(item)
    check(
        "custom_conflict_removal_detected", not shortcuts.conflicts(bpy.context.window_manager, "A")
    )

    # An ordinary Text datablock must retain native Enter = newline.
    area.type = "TEXT_EDITOR"
    ordinary = bpy.data.texts.new("Ordinary script")
    area.spaces.active.text = ordinary
    yield 0.3
    type_text("line")
    key("RET")
    yield 0.3
    check(
        "ordinary_text_enter_is_untouched",
        ordinary.as_string() == "line\n" and area.type == "TEXT_EDITOR",
    )
    area.type = "VIEW_3D"
    yield 0.3
    # Native draft surface metadata survives a lost transient cache.
    cube.data.calc_loop_triangles()
    triangle = cube.data.loop_triangles[0]
    point = sum((cube.data.vertices[i].co for i in triangle.vertices), Vector()) / 3
    token = ui.prepare_add(scene, cube, triangle.index, point, api.geometry(cube)[1])
    with bpy.context.temp_override(window=window, area=area, region=region):
        editor.open_pending(bpy.context, token)
    ui._pending.clear()
    yield 0.3
    type_text("Recovered creation draft")
    key("RET")
    yield 0.5
    check(
        "creation_draft_recovers_surface_without_python_cache",
        len(api.marks(scene)) == 4 and area.type == "VIEW_3D",
    )
    check(
        "new_color_does_not_repeat_after_review",
        len({tuple(mark.color) for mark in api.marks(scene)}) == 4,
    )
    # Enum ordinals are part of the persisted file format.
    check(
        "old_status_ordinals_preserved",
        [
            (item.identifier, item.value)
            for item in type(mark).bl_rna.properties["status"].enum_items
        ][:4]
        == [("OPEN", 0), ("IN_PROGRESS", 1), ("RESOLVED", 2), ("ARCHIVED", 3)],
    )
    original_anchor = api.serialize(scene, mark)["resolved"]["world_position"]
    cube.data.vertices.add(1)
    cube.data.update()
    bpy.context.view_layer.update()
    viewport.focus_mark(scene, mark, view)
    check(
        "topology_edit_still_allows_review_focus_at_reference",
        (space.region_3d.view_location - Vector(original_anchor)).length < 1e-5
        and api.serialize(scene, mark)["resolved"]["state"] == "STALE_TOPOLOGY"
        and api.serialize(scene, mark)["resolved"]["world_position"] is None,
    )


runner = steps()


def tick():
    global scene, cube, view, window, area, region, space
    try:
        scene = bpy.context.scene
        cube = scene.objects["Cube"]
        window = floating.current_window() or bpy.context.window_manager.windows[0]
        area = max(
            (a for a in window.screen.areas if a.type in {"VIEW_3D", "TEXT_EDITOR"}),
            key=lambda a: a.width * a.height,
        )
        region = next(r for r in area.regions if r.type == "WINDOW")
        space = next(s for s in area.spaces if s.type == "VIEW_3D")
        view = viewport.ViewportContext(window, area, region, space)
        return next(runner)
    except StopIteration:
        (OUT / "review_test_report.json").write_text(
            json.dumps({"checks_passed": len(checks), "checks": checks}, indent=2), encoding="utf-8"
        )
    except Exception:
        (OUT / "review_test_error.txt").write_text(
            traceback.format_exc() + "\n" + json.dumps(checks), encoding="utf-8"
        )
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(tick, first_interval=2)
