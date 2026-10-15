"""Native title dragging preserves drafts and shares placement across note flows."""

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


def mouse(kind, value, x, y):
    window.event_simulate(type=kind, value=value, x=int(x), y=int(y))


def drag(dx, dy):
    from blender_agent_marks import compact

    session = compact.SESSION
    x, y, width, height = session.bounds
    px, py = x + width / 2, y + height - 1.3 * session.unit
    mouse("MOUSEMOVE", "NOTHING", px, py)
    mouse("LEFTMOUSE", "PRESS", px, py)
    yield 0.1
    mouse("MOUSEMOVE", "NOTHING", px + dx, py + dy)
    yield 0.1
    mouse("LEFTMOUSE", "RELEASE", px + dx, py + dy)
    yield 0.2


def steps():
    from blender_agent_marks import compact

    token = ui.prepare_add(scene, obj, 0, point, api.geometry(obj)[1])
    with bpy.context.temp_override(window=window, area=area, region=region):
        editor.open_pending(bpy.context, token)
    yield 0.4
    check("default_lower_middle", compact.read_position() == (0.5, 0.3))
    first_session = compact.SESSION
    initial = first_session.anchor
    yield from drag(0, 10)
    check(
        "empty_note_drags_without_typing", compact.SESSION is first_session and not api.marks(scene)
    )
    yield from drag(0, -10)
    # Refocus the native field after dragging; moving the title does not edit text.
    x, y, width, height = compact.SESSION.bounds
    mouse("MOUSEMOVE", "NOTHING", x + width / 2, y + height - 4.5 * compact.SESSION.unit)
    yield 0.1
    mouse("LEFTMOUSE", "PRESS", x + width / 2, y + height - 4.5 * compact.SESSION.unit)
    mouse("LEFTMOUSE", "RELEASE", x + width / 2, y + height - 4.5 * compact.SESSION.unit)
    yield 0.1
    type_text("拖动前 Draft text")
    yield 0.2
    session = compact.SESSION
    check("initial_popup_has_geometry", session.bounds is not None)
    x, y, w, h = session.bounds
    px, py = x + w / 2, y + h - 1.3 * session.unit
    mouse("MOUSEMOVE", "NOTHING", px, py)
    yield 0.1
    mouse("LEFTMOUSE", "PRESS", px, py)
    yield 0.1
    mouse("MOUSEMOVE", "NOTHING", px + 150, py + 90)
    yield 0.2
    bpy.ops.screen.screenshot(filepath=str(OUT / "drag_during.png"))
    mouse("LEFTMOUSE", "RELEASE", px + 150, py + 90)
    yield 0.5

    check("drag_moves_popup", compact.SESSION.anchor == (initial[0] + 150, initial[1] + 90))
    check("drag_preserves_input", bpy.context.window_manager.asm_note_input == "拖动前 Draft text")
    check("drag_does_not_create_mark", not api.marks(scene))
    bpy.ops.screen.screenshot(filepath=str(OUT / "drag_after.png"))
    session = compact.SESSION
    x, y, w, h = session.bounds
    px, py = x + w / 2, y + h - 1.3 * session.unit
    mouse("MOUSEMOVE", "NOTHING", px, py)
    mouse("LEFTMOUSE", "PRESS", px, py)
    yield 0.1
    mouse("MOUSEMOVE", "NOTHING", px + 25, py + 20)
    yield 0.1
    mouse("LEFTMOUSE", "RELEASE", px + 25, py + 20)
    yield 0.2
    check(
        "continuous_drag_moves_same_popup",
        compact.SESSION is session
        and compact.SESSION.anchor == (initial[0] + 175, initial[1] + 110),
    )
    key("RET")
    yield 0.3
    check(
        "enter_after_drag_creates_note",
        len(api.marks(scene)) == 1 and api.marks(scene)[0].note == "拖动前 Draft text",
    )
    call(bpy.ops.asm.edit, marker_id=api.marks(scene)[0].marker_id)
    yield 0.4
    check(
        "next_popup_reuses_position", compact.SESSION.anchor == (initial[0] + 175, initial[1] + 110)
    )
    key("ESC")
    yield 0.2
    check("escape_cleans_popup_session", compact.SESSION is None)
    marker_id = api.marks(scene)[0].marker_id
    saved_position = compact.read_position()
    check("position_persisted_outside_scene", compact.position_path().is_file())
    call(bpy.ops.asm.edit, marker_id=marker_id)
    yield 0.3
    yield from drag(-35, 20)
    expected = compact.SESSION.anchor
    key("ESC")
    yield 0.2
    check("cancel_keeps_dragged_position", compact.read_position() != saved_position)
    check(
        "cancel_drag_keeps_original_note",
        api.get_mark(scene, marker_id).note == "拖动前 Draft text",
    )
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
    check("reject_shares_saved_position", compact.SESSION.anchor == expected)
    key("ESC")
    yield 0.2
    mark = api.get_mark(scene, marker_id)
    api.update(scene, marker_id, mark.revision, note="第一行\nSecond line")
    call(bpy.ops.asm.edit, marker_id=marker_id)
    yield 0.3
    yield from drag(-20, -15)
    check(
        "multiline_preview_drag_preserves_lines",
        bpy.context.window_manager.asm_note_draft.as_string() == "第一行\nSecond line",
    )
    key("RET")
    yield 0.3
    check(
        "multiline_drag_enter_closes",
        compact.SESSION is None and api.get_mark(scene, marker_id).note == "第一行\nSecond line",
    )
    call(bpy.ops.asm.edit, marker_id=marker_id)
    yield 0.3
    x, y, width, height = compact.SESSION.bounds
    px, py = x + width / 2, y + 3.1 * compact.SESSION.unit
    bpy.ops.screen.screenshot(filepath=str(OUT / "multiline_popup_preview.png"))
    mouse("MOUSEMOVE", "NOTHING", px, py)
    yield 0.1
    mouse("LEFTMOUSE", "PRESS", px, py)
    mouse("LEFTMOUSE", "RELEASE", px, py)
    yield 0.5
    check(
        "explicit_expand_closes_popup",
        compact.SESSION is None and len(bpy.context.window_manager.windows) == 2,
    )
    expanded = next(w for w in bpy.context.window_manager.windows if w != window)
    with bpy.context.temp_override(window=expanded):
        bpy.ops.wm.window_close()
    yield 0.2
    call(bpy.ops.asm.edit, marker_id=marker_id)
    yield 0.3
    mouse("LEFTMOUSE", "PRESS", 20, 200)
    mouse("LEFTMOUSE", "RELEASE", 20, 200)
    yield 0.3
    check("outside_click_cleans_session", compact.SESSION is None)
    compact.position_path().write_text('{"note_position":["invalid",null]}', encoding="utf-8")
    check("invalid_position_uses_default", compact.read_position() == (0.5, 0.3))


runner = steps()


def tick():
    global scene, obj
    try:
        scene = bpy.context.scene
        obj = scene.objects["Cube"]
        return next(runner)
    except StopIteration:
        (OUT / "drag_test_report.json").write_text(
            json.dumps({"checks_passed": len(checks), "checks": checks}, indent=2), encoding="utf-8"
        )
    except Exception:
        with bpy.context.temp_override(window=window):
            bpy.ops.screen.screenshot(filepath=str(OUT / "compact_note_failure.png"))
        (OUT / "drag_test_error.txt").write_text(
            traceback.format_exc() + "\n" + json.dumps(checks), encoding="utf-8"
        )
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(tick, first_interval=2)
