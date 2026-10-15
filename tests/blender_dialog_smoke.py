"""Default note entry remains compact and accepts native keyboard input."""

import json
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import blender_agent_marks
from blender_agent_marks import api, editor, review, ui, viewport

OUT = ROOT / "artifacts"
blender_agent_marks.register()
bpy.context.preferences.view.show_splash = False
scene = bpy.context.scene
obj = scene.objects["Cube"]
obj.data.calc_loop_triangles()
point = sum((obj.data.vertices[i].co for i in obj.data.loop_triangles[0].vertices), Vector()) / 3
window, area, region, space = next(viewport.viewports(scene))
checks = []


def check(name, condition):
    assert condition, name
    checks.append(name)


def call(operator, **arguments):
    with bpy.context.temp_override(window=window, area=area, region=region):
        return operator("INVOKE_DEFAULT", **arguments)


def key(kind, **arguments):
    window.event_simulate(
        type=kind, value="PRESS", x=window.width // 2, y=window.height // 3, **arguments
    )
    arguments.pop("unicode", None)
    window.event_simulate(
        type=kind, value="RELEASE", x=window.width // 2, y=window.height // 3, **arguments
    )


def type_text(value):
    for character in value:
        key("A", unicode=character)


def steps():
    view_matrix = space.region_3d.view_matrix.copy()
    layout = [(a.as_pointer(), a.type, a.width, a.height) for a in window.screen.areas]
    token = ui.prepare_add(scene, obj, 0, point, api.geometry(obj)[1])
    with bpy.context.temp_override(window=window, area=area, region=region):
        editor.open_pending(bpy.context, token)
    yield 0.4
    check("placement_opens_no_additional_window", len(bpy.context.window_manager.windows) == 1)
    check(
        "placement_preserves_main_layout",
        layout == [(a.as_pointer(), a.type, a.width, a.height) for a in window.screen.areas],
    )
    type_text("圆角 Round edge")
    yield 0.2
    check("typing_does_not_publish_draft", not api.marks(scene))
    with bpy.context.temp_override(window=window):
        bpy.ops.screen.screenshot(filepath=str(OUT / "compact_note_preview.png"))
    key("RET")
    yield 0.4
    check(
        "one_enter_creates_note",
        len(api.marks(scene)) == 1 and api.marks(scene)[0].note == "圆角 Round edge",
    )
    marker_id = api.marks(scene)[0].marker_id
    xray_before = space.shading.show_xray
    key("Z", alt=True)
    yield 0.2
    check("enter_closes_popup_and_restores_viewport_keys", space.shading.show_xray != xray_before)
    key("Z", alt=True)
    yield 0.2
    check(
        "confirmed_creation_draft_removed", not any(editor.DRAFT_KEY in t for t in bpy.data.texts)
    )
    call(bpy.ops.asm.edit, marker_id=marker_id)
    yield 0.3
    check("editing_stays_in_main_window", len(bpy.context.window_manager.windows) == 1)
    key("A", ctrl=True)
    type_text("Edited 中文")
    key("RET")
    yield 0.4
    check("one_enter_updates_note", api.get_mark(scene, marker_id).note == "Edited 中文")
    key("Z", ctrl=True)
    yield 0.3
    check("compact_edit_is_undoable", api.get_mark(scene, marker_id).note == "圆角 Round edge")
    key("Z", ctrl=True, shift=True)
    yield 0.3
    check("compact_edit_is_redoable", api.get_mark(scene, marker_id).note == "Edited 中文")
    call(bpy.ops.asm.edit, marker_id=marker_id)
    yield 0.3
    type_text("Discard")
    key("ESC")
    yield 0.3
    check("escape_keeps_original_note", api.get_mark(scene, marker_id).note == "Edited 中文")
    review.submit_changes(
        [
            {
                "scene_name": scene.name,
                "marker_id": marker_id,
                "expected_revision": api.get_mark(scene, marker_id).revision,
                "summary": "Done",
            }
        ]
    )
    call(bpy.ops.asm.review, action="REJECT")
    yield 0.3
    check("reject_uses_compact_dialog", len(bpy.context.window_manager.windows) == 1)
    key("A", ctrl=True)
    type_text("Revise this edge")
    key("RET")
    yield 0.4
    check(
        "reject_commits_note_and_state",
        api.get_mark(scene, marker_id).note == "Revise this edge"
        and api.get_mark(scene, marker_id).status == "CHANGES_REQUESTED",
    )
    multiline = "第一行\nSecond line"
    mark = api.get_mark(scene, marker_id)
    api.update(scene, marker_id, mark.revision, note=multiline)
    call(bpy.ops.asm.edit, marker_id=marker_id)
    yield 0.3
    check("existing_multiline_does_not_auto_expand", len(bpy.context.window_manager.windows) == 1)
    key("RET")
    yield 0.3
    check(
        "multiline_preview_preserves_line_breaks", api.get_mark(scene, marker_id).note == multiline
    )
    check(
        "multiline_enter_confirms_without_expansion",
        len(bpy.context.window_manager.windows) == 1
        and bpy.context.window_manager.asm_note_draft is None,
    )
    check("view_matrix_preserved", space.region_3d.view_matrix == view_matrix)
    mark = api.get_mark(scene, marker_id)
    api.update(scene, marker_id, mark.revision, note="Before conflict")
    call(bpy.ops.asm.edit, marker_id=marker_id)
    yield 0.3
    type_text("My draft")
    mark = api.get_mark(scene, marker_id)
    api.update(scene, marker_id, mark.revision, note="Newer edit")
    key("RET")
    yield 0.3
    check(
        "compact_conflict_preserves_newer_note", api.get_mark(scene, marker_id).note == "Newer edit"
    )
    check("compact_conflict_retains_input", editor.find_draft(marker_id).as_string() == "My draft")


runner = steps()


def tick():
    global scene, obj
    try:
        scene = bpy.context.scene
        obj = scene.objects["Cube"]
        return next(runner)
    except StopIteration:
        (OUT / "dialog_test_report.json").write_text(
            json.dumps({"checks_passed": len(checks), "checks": checks}, indent=2), encoding="utf-8"
        )
    except Exception:
        with bpy.context.temp_override(window=window):
            bpy.ops.screen.screenshot(filepath=str(OUT / "compact_note_failure.png"))
        (OUT / "dialog_test_error.txt").write_text(
            traceback.format_exc() + "\n" + json.dumps(checks), encoding="utf-8"
        )
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(tick, first_interval=2)
