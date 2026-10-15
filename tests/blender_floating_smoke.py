"""Blender-managed editor: main view, native input, commit and cancellation."""

import json
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import blender_agent_marks
from blender_agent_marks import api, editor, floating, ui, viewport

OUT = ROOT / "artifacts"
blender_agent_marks.register()
bpy.context.preferences.view.show_splash = False
scene = bpy.context.scene
obj = scene.objects["Cube"]
obj.data.calc_loop_triangles()
point = sum((obj.data.vertices[i].co for i in obj.data.loop_triangles[0].vertices), Vector()) / 3
mark = api.create(scene, obj.name, 0, point, "Original 中文\nSecond line")
owner, area, region, space = next(viewport.viewports(scene))
checks = []


def check(name, condition):
    assert condition, name
    checks.append(name)


def call(operator, **arguments):
    window = floating.current_window() or owner
    target = window.screen.areas[0] if floating.is_editor(window) else area
    r = next(r for r in target.regions if r.type == "WINDOW")
    with bpy.context.temp_override(window=window, area=target, region=r):
        return operator("EXEC_DEFAULT", True, **arguments)


def key(kind, **arguments):
    window = floating.current_window() or owner
    window.event_simulate(type=kind, value="PRESS", x=80, y=90, **arguments)
    arguments.pop("unicode", None)
    window.event_simulate(type=kind, value="RELEASE", x=80, y=90, **arguments)


def type_text(value):
    for character in value:
        key("A", unicode=character)


def steps():
    selection = [obj.name for obj in bpy.context.selected_objects]
    view_matrix = space.region_3d.view_matrix.copy()
    call(bpy.ops.asm.edit_multiline, marker_id=mark["id"])
    yield 0.4
    window = floating.current_window()
    check(
        "original_viewport_is_preserved",
        area.type == "VIEW_3D" and space.region_3d.view_matrix == view_matrix,
    )
    check("separate_native_editor_window", window is not None and window != owner)
    check("native_text_editor", window.screen.areas[0].type == "TEXT_EDITOR")
    draft = window.screen.areas[0].spaces.active.text
    check("multiline_original_preserved", draft.as_string() == mark["note"])
    previous_pointer = window.as_pointer()
    with bpy.context.temp_override(window=owner, area=area, region=region):
        bpy.ops.asm.edit_multiline("EXEC_DEFAULT", marker_id=mark["id"])
    yield 0.4
    window = floating.current_window()
    check(
        "opening_from_main_uses_focused_native_window",
        window.as_pointer() != previous_pointer and len(bpy.context.window_manager.windows) == 2,
    )
    check("reopened_window_preserves_draft", window.screen.areas[0].spaces.active.text == draft)
    key("A", ctrl=True)
    type_text("改为圆角")
    key("RET", shift=True)
    type_text("Keep the width")
    yield 0.25
    check("native_typing_and_shift_enter", draft.as_string() == "改为圆角\nKeep the width")
    check("draft_not_exposed_to_agent", api.get_mark(scene, mark["id"]).note == mark["note"])
    with bpy.context.temp_override(window=window):
        bpy.ops.screen.screenshot(filepath=str(OUT / "floating_note_preview.png"))
    key("RET")
    yield 0.5
    check(
        "single_enter_saves_and_closes",
        floating.current_window() is None
        and len(bpy.context.window_manager.windows) == 1
        and api.get_mark(scene, mark["id"]).note == "改为圆角\nKeep the width",
    )
    check("selection_is_preserved", selection == [obj.name for obj in bpy.context.selected_objects])
    call(bpy.ops.asm.edit_multiline, marker_id=mark["id"])
    yield 0.4
    type_text("Cancel this")
    key("ESC")
    yield 0.4
    check(
        "escape_cancels_and_closes",
        floating.current_window() is None
        and api.get_mark(scene, mark["id"]).note == "改为圆角\nKeep the width",
    )
    token = ui.prepare_add(scene, obj, 0, point, api.geometry(obj)[1])
    with bpy.context.temp_override(window=owner, area=area, region=region):
        editor.open_pending(bpy.context, token, expanded=True)
    yield 0.4
    check(
        "new_marker_uses_native_editor",
        area.type == "VIEW_3D" and floating.current_window() is not None,
    )
    type_text("New annotation")
    key("RET")
    yield 0.4
    check(
        "creation_single_enter_commits_once",
        len(api.marks(scene)) == 2
        and api.marks(scene)[-1].note == "New annotation"
        and floating.current_window() is None,
    )


runner = steps()


def tick():
    try:
        return next(runner)
    except StopIteration:
        (OUT / "floating_test_report.json").write_text(
            json.dumps({"checks_passed": len(checks), "checks": checks}, indent=2), encoding="utf-8"
        )
    except Exception:
        (OUT / "floating_test_error.txt").write_text(
            traceback.format_exc() + "\n" + json.dumps(checks), encoding="utf-8"
        )
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(tick, first_interval=2)
