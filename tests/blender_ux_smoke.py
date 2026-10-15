"""Isolated real UI regression; launch Blender with --enable-event-simulate."""

import json
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import blender_agent_marks
from blender_agent_marks import api, connection, editor, floating, runtime, ui, ux, viewport

OUT = ROOT / "artifacts"
for filename in ("ux_test_report.json", "ux_test_error.txt", "ux_failure.png"):
    (OUT / filename).unlink(missing_ok=True)
checks = []
blender_agent_marks.register()
bpy.context.preferences.view.show_splash = False
scene = bpy.context.scene
obj = bpy.data.objects["Cube"]
obj.name = "外壳 · 表面注释演示"
obj.data.calc_loop_triangles()
notes = ["将这条边改为圆角。\n保留面板宽度，避免影响旁边的卡扣。", "此处保持平整", "增加一条浅凹槽"]
for point, note in zip(((-0.6, -0.5, 1), (0.35, 0.15, 1), (-0.45, 0.7, 1)), notes):
    for tri in obj.data.loop_triangles:
        if tri.normal.z < 0.9:
            continue
        try:
            api.create(scene, obj.name, tri.index, point, note)
            break
        except api.MarkError:
            pass
api.document(scene).asm_active_index = 0
view = next(viewport.viewports(scene))
window, area, region, space = view
space.shading.type = "SOLID"
space.overlay.show_floor = False
space.overlay.show_axis_x = False
space.overlay.show_axis_y = False
space.region_3d.view_rotation = Quaternion((1, 0, 0, 0))
space.region_3d.view_distance = 7
space.region_3d.view_location = (0, 0, 0)
space.region_3d.view_perspective = "ORTHO"
space.show_region_ui = True
wm = bpy.context.window_manager
first_id = api.marks(scene)[0].marker_id
second_id = api.marks(scene)[1].marker_id


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)


def event(kind, value="PRESS", x=None, y=None, **kwargs):
    window.event_simulate(
        type=kind,
        value=value,
        x=int(x if x is not None else region.x + 100),
        y=int(y if y is not None else region.y + 100),
        **kwargs,
    )


def click(x, y):
    event("MOUSEMOVE", "NOTHING", x, y)
    event("LEFTMOUSE", "PRESS", x, y)
    event("LEFTMOUSE", "RELEASE", x, y)


def key(kind, **kwargs):
    event(kind, **kwargs)
    event(kind, "RELEASE", **kwargs)


def replace_text(value):
    key("A", ctrl=True)
    for char in value:
        event("A", unicode=char)
        event("A", "RELEASE")


def invoke_edit(identifier):
    r = next(r for r in area.regions if r.type == "WINDOW")
    with bpy.context.temp_override(window=window, area=area, region=r):
        return bpy.ops.asm.edit("INVOKE_DEFAULT", marker_id=identifier)


def call(operator, **kwargs):
    r = next(r for r in area.regions if r.type == "WINDOW")
    with bpy.context.temp_override(window=window, area=area, region=r):
        return operator("EXEC_DEFAULT", True, **kwargs)


def mark_xy(index):
    state = api.serialize(scene, api.marks(scene)[index], view)["viewport"]
    return state["screen_px"][0] + region.x, state["screen_px"][1] + region.y


def steps():
    for r in area.regions:
        if r.type == "UI":
            r.active_panel_category = "FacetCue for Blender"
    # Registering operators can emit nonfatal RNA errors: assert usable properties.
    check("add_dialog_registered", "token" in bpy.ops.asm.add_note.get_rna_type().properties)
    wm.asm_search = "圆角"
    check("search_by_note", sum(ux.matches(m, wm) for m in api.marks(scene)) == 1)
    wm.asm_search = "M0002"
    check("search_by_number", ux.matches(api.marks(scene)[1], wm))
    wm.asm_search = obj.name
    check("search_by_object", all(ux.matches(m, wm) for m in api.marks(scene)))
    wm.asm_filter = "RESOLVED"
    result = api.dispatch("get_surface_annotations")
    check(
        "filter_never_hides_agent_data",
        result["total"] == 3
        and all(not m["viewport"]["overlay_drawn"] for m in result["annotations"]),
    )
    wm.asm_filter = "ALL"
    wm.asm_search = ""
    # A hit selects a marker while leaving modeling selection alone.
    for o in scene.objects:
        o.select_set(False)
    light = bpy.data.objects["Light"]
    light.select_set(True)
    window.view_layer.objects.active = light
    selected_before = {o.name for o in bpy.context.selected_objects}
    click(*mark_xy(1))
    yield 1
    check("real_click_selects_marker", ux.active_mark(scene).marker_id == second_id)
    check(
        "marker_click_preserves_object_selection",
        {o.name for o in bpy.context.selected_objects} == selected_before,
    )
    # A plain surface click must reach the ordinary Blender selection operator.
    center = space.region_3d.perspective_matrix @ Vector((0.65, -0.7, 1, 1))
    x, y = (
        (center.x / center.w + 1) * region.width / 2 + region.x,
        (center.y / center.w + 1) * region.height / 2 + region.y,
    )
    click(x, y)
    yield 1
    check(
        "non_marker_click_selects_mesh_normally",
        window.view_layer.objects.active == obj and obj.select_get(),
    )
    # Invoke placement via its actual shortcut, miss once, then open/cancel dialog.
    before = len(api.marks(scene))
    key("A", ctrl=True, alt=True, shift=True)
    yield 0.5
    click(region.x + 90, region.y + 90)
    yield 0.5
    check("miss_does_not_create_mark", len(api.marks(scene)) == before)
    click(x, y)
    yield 0.5
    check("placement_dialog_is_pending", len(ui._pending) == 1 and len(api.marks(scene)) == before)
    key("ESC")
    yield 0.5
    if ui._pending:  # Blender's first Esc exits active text entry.
        key("ESC")
        yield 0.5
    check(
        "cancel_dialog_leaves_no_mark_or_pending",
        len(api.marks(scene)) == before and not ui._pending,
    )
    # Immediate typing in a newly opened dialog, then confirm (no second field click).
    key("A", ctrl=True, alt=True, shift=True)
    yield 0.5
    click(x, y)
    yield 0.5
    for char in "Round this corner":
        event("A", unicode=char)
        event("A", "RELEASE")
    key("RET")
    yield 0.5
    check(
        "dialog_typing_creates_note",
        len(api.marks(scene)) == before + 1 and api.marks(scene)[-1].note == "Round this corner",
    )
    key("Z", ctrl=True)
    yield 1
    check("create_is_undoable", len(api.marks(scene)) == before)
    # Double-click the existing single-line note: edit in place, never recreate.
    original = api.serialize(scene, api.get_mark(scene, second_id))
    selected_before = {o.name for o in bpy.context.selected_objects}
    mx, my = mark_xy(1)
    click(mx, my)
    yield 0.08
    click(mx, my)
    yield 0.5
    bpy.ops.screen.screenshot(filepath=str(OUT / "edit_entry_preview.png"))
    replace_text("Keep this surface flat; soften the edge")
    key("RET")
    yield 0.5
    edited = api.serialize(scene, api.get_mark(scene, second_id))
    check(
        "double_click_edits_existing_entry",
        edited["note"] == "Keep this surface flat; soften the edge",
    )
    check(
        "edit_preserves_identity_color_anchor",
        all(
            edited[k] == original[k]
            for k in ("id", "label", "color_rgba", "anchor", "target", "resolved")
        ),
    )
    check("edit_increments_revision_once", edited["revision"] == original["revision"] + 1)
    check(
        "edit_preserves_object_selection",
        {o.name for o in bpy.context.selected_objects} == selected_before,
    )
    scope = {}
    scope["result"] = api.dispatch("get_surface_annotations")
    check(
        "edited_entry_immediately_readable_through_annotation_api",
        next(m for m in scope["result"]["annotations"] if m["id"] == second_id)["note"]
        == edited["note"],
    )
    key("Z", ctrl=True)
    yield 1
    check("quick_edit_undo", api.get_mark(scene, second_id).note == original["note"])
    key("Z", ctrl=True, shift=True)
    yield 1
    check("quick_edit_redo", api.get_mark(scene, second_id).note == edited["note"])
    # Row pencil passes an explicit ID, independent of the selected list item.
    api.document(scene).asm_active_index = 0
    check("explicit_entry_opens_editor", invoke_edit(second_id) == {"FINISHED"})
    yield 0.5
    check("explicit_entry_selects_correct_marker", ux.active_mark(scene).marker_id == second_id)
    replace_text("Discard these changes")
    key("ESC")
    yield 0.5
    key("ESC")
    yield 0.5
    check(
        "quick_edit_cancel_preserves_note_and_revision",
        api.serialize(scene, api.get_mark(scene, second_id))["note"] == edited["note"]
        and api.get_mark(scene, second_id).revision == edited["revision"],
    )
    # Existing multiline notes must never pass through a single-line field.
    api.document(scene).asm_active_index = 1
    check("multiline_entry_opens_compact_preview", invoke_edit(first_id) == {"FINISHED"})
    yield 0.5
    draft = wm.asm_note_draft
    check(
        "multiline_entry_keeps_original_line_breaks",
        area.type == "VIEW_3D" and len(wm.windows) == 1 and draft.as_string() == notes[0],
    )
    key("ESC")
    yield 0.3
    call(bpy.ops.asm.edit_multiline, marker_id=first_id)
    yield 0.4
    draft = area.spaces.active.text
    draft.write("\n保留未完成草稿")
    draft_name = draft.name
    with bpy.context.temp_override(window=window):
        bpy.ops.wm.window_close()
    yield 0.4
    invoke_edit(first_id)
    yield 0.5
    check(
        "edit_resumes_existing_draft",
        area.type == "VIEW_3D"
        and wm.asm_note_draft.name == draft_name
        and "保留未完成草稿" in wm.asm_note_draft.as_string(),
    )
    key("ESC")
    yield 0.5
    # Saving targets the original scene even when context has since changed.
    other_scene = bpy.data.scenes.new("Different editing context")
    mark = api.get_mark(scene, second_id)
    with bpy.context.temp_override(scene=other_scene):
        outcome = bpy.ops.asm.edit(
            "EXEC_DEFAULT",
            scene_name=scene.name,
            marker_id=second_id,
            expected_revision=mark.revision,
            note=edited["note"],
            status="IN_PROGRESS",
        )
    check(
        "edit_targets_pinned_scene",
        outcome == {"FINISHED"}
        and api.get_mark(scene, second_id).status == "IN_PROGRESS"
        and len(api.marks(other_scene)) == 0,
    )
    stale_revision = mark.revision - 1
    check(
        "stale_edit_does_not_overwrite",
        call(
            bpy.ops.asm.edit,
            marker_id=second_id,
            expected_revision=stale_revision,
            note="Stale write",
            status="OPEN",
        )
        == {"CANCELLED"}
        and api.get_mark(scene, second_id).note == edited["note"],
    )
    check(
        "stale_quick_edit_preserves_input_as_draft",
        editor.find_draft(second_id).as_string() == "Stale write",
    )
    invoke_edit(second_id)
    yield 0.5
    key("ESC")
    yield 0.5
    other_scene = bpy.data.scenes["Different editing context"]
    bpy.data.scenes.remove(other_scene)
    # Never retain pre-Undo RNA references to the registry or marks.
    api.document(scene).asm_active_index = 0
    call(bpy.ops.asm.edit_multiline)
    yield 0.5
    draft = area.spaces.active.text
    check(
        "native_multiline_editor",
        area.type == "TEXT_EDITOR"
        and area.spaces.active.show_word_wrap
        and not area.spaces.active.use_live_edit,
    )
    new_note = "将这条边改为圆角。\n半径控制在 2 mm 左右。\n保留面板宽度，避免影响旁边的卡扣。"
    draft.clear()
    draft.write(new_note)
    check("draft_not_visible_to_agent_before_save", api.get_mark(scene, first_id).note != new_note)
    draft.cursor_set(0, character=0)
    area.spaces.active.top = 0
    area.tag_redraw()
    yield 0.5
    bpy.ops.screen.screenshot(filepath=str(OUT / "note_editor_preview.png"))
    saved_draft_name = draft.name
    key("RET", ctrl=True)
    yield 1
    check(
        "ctrl_enter_saves_and_returns",
        area.type == "VIEW_3D" and api.get_mark(scene, first_id).note == new_note,
    )
    check("saved_draft_removed", bpy.data.texts.get(saved_draft_name) is None)
    call(bpy.ops.asm.edit_multiline)
    yield 0.5
    draft = area.spaces.active.text
    draft.write("\n我正在编辑的草稿")
    mark = api.get_mark(scene, first_id)
    api.update(scene, first_id, mark.revision, note=new_note + "\n并发修改")
    check(
        "conflict_keeps_draft",
        call(bpy.ops.asm.apply_draft) == {"CANCELLED"}
        and area.type == "TEXT_EDITOR"
        and "我正在编辑" in draft.as_string(),
    )
    check("conflict_does_not_overwrite", api.get_mark(scene, first_id).note.endswith("并发修改"))
    call(bpy.ops.asm.cancel_draft)
    yield 0.5
    check(
        "cancel_keeps_original",
        area.type == "VIEW_3D" and api.get_mark(scene, first_id).note.endswith("并发修改"),
    )
    mark = api.get_mark(scene, first_id)
    # Establish the baseline through a UI operator. Direct API writes deliberately
    # do not insert Blender Undo snapshots.
    call(
        bpy.ops.asm.edit,
        marker_id=first_id,
        expected_revision=mark.revision,
        note=new_note,
        status=mark.status,
    )
    call(bpy.ops.asm.set_status, status="RESOLVED")
    yield 0.5
    check("resolve_one_click", api.get_mark(scene, first_id).status == "RESOLVED")
    key("Z", ctrl=True)
    yield 1
    check("status_is_undoable", api.get_mark(scene, first_id).status == "OPEN")
    check("undo_status_preserves_saved_note", api.get_mark(scene, first_id).note == new_note)
    api.document(scene).asm_active_index = next(
        i for i, m in enumerate(api.marks(scene)) if m.marker_id == first_id
    )
    call(bpy.ops.asm.set_status, status="ARCHIVED")
    check(
        "archive_keeps_agent_note",
        any(
            m["id"] == first_id and m["status"] == "ARCHIVED"
            for m in api.dispatch("get_surface_annotations")["annotations"]
        ),
    )
    call(bpy.ops.asm.set_status, status="OPEN")
    # Undo can replace Scene/Object datablocks: reacquire view and object globally.
    camera = scene.camera
    camera_before = camera.matrix_world.copy()
    selected_before = [o.name for o in bpy.context.selected_objects]
    space.region_3d.view_perspective = "CAMERA"
    call(bpy.ops.asm.focus)
    yield 0.5
    point = api.resolve(scene, api.get_mark(scene, first_id))["world_position"]
    check("focus_centers_surface", (space.region_3d.view_location - Vector(point)).length < 1e-5)
    check(
        "focus_preserves_camera_and_selection",
        camera.matrix_world == camera_before
        and selected_before == [o.name for o in bpy.context.selected_objects],
    )
    check("focus_exits_camera_view", space.region_3d.view_perspective != "CAMERA")
    # The connection's read receipt must not dirty the file.
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "ux_demo.blend"))
    was_dirty = bpy.data.is_dirty
    connection._server.dispatch(
        {"protocol": 1, "token": connection._server.token, "operation": "get_surface_annotations"}
    )
    check(
        "mcp_receipt_recorded", runtime.LAST_AGENT_READ and runtime.LAST_AGENT_READ["returned"] == 3
    )
    check("read_receipt_does_not_dirty_file", bpy.data.is_dirty == was_dirty)
    wm.asm_show_overlay = False
    check(
        "hidden_overlay_still_one_call_readable",
        api.dispatch("get_surface_annotations")["total"] == 3,
    )
    wm.asm_show_overlay = True
    # Return to an overview for the delivery screenshot.
    space.region_3d.view_rotation = Quaternion((1, 0, 0, 0))
    space.region_3d.view_location = (0, 0, 0)
    space.region_3d.view_distance = 7
    space.region_3d.view_perspective = "ORTHO"
    for o in scene.objects:
        o.select_set(False)
    area.tag_redraw()
    yield 0.5
    bpy.ops.screen.screenshot(filepath=str(OUT / "ux_viewport_preview.png"))
    check(
        "screenshots_saved",
        (OUT / "note_editor_preview.png").exists() and (OUT / "ux_viewport_preview.png").exists(),
    )
    keymap_count = len(ui._keymaps)
    blender_agent_marks.unregister()
    check(
        "disable_removes_ui_handlers",
        ui._handle is None
        and not ui._keymaps
        and ux.invalidate not in bpy.app.handlers.depsgraph_update_post,
    )
    blender_agent_marks.register()
    check(
        "reenable_restores_single_ui_registration",
        len(ui._keymaps) == keymap_count and api.dispatch("get_surface_annotations")["total"] == 3,
    )


runner = steps()


def tick():
    global scene, obj, view, window, area, region, space, wm
    try:
        # Global undo invalidates RNA pointers, even for unchanged objects.
        scene = bpy.context.scene
        obj = scene.objects.get("外壳 · 表面注释演示")
        wm = bpy.context.window_manager
        window = floating.current_window() or wm.windows[0]
        # The main editor survives layout switching but not necessarily undo.
        area = max(
            (a for a in window.screen.areas if a.type in {"VIEW_3D", "TEXT_EDITOR"}),
            key=lambda a: a.width * a.height,
        )
        region = next(r for r in area.regions if r.type == "WINDOW")
        space = next(s for s in area.spaces if s.type == "VIEW_3D")
        view = window, area, region, space
        return next(runner)
    except StopIteration:
        (OUT / "ux_test_report.json").write_text(
            json.dumps(
                {"blender": bpy.app.version_string, "checks_passed": len(checks), "checks": checks},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        bpy.ops.wm.quit_blender()
    except Exception:
        (OUT / "ux_test_error.txt").write_text(
            traceback.format_exc() + "\n" + json.dumps(checks), encoding="utf-8"
        )
        bpy.ops.screen.screenshot(filepath=str(OUT / "ux_failure.png"))
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(tick, first_interval=3)
