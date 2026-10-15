"""Delete confirmation, real shortcut input and Undo in an isolated Blender GUI."""

import json
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import blender_agent_marks
from blender_agent_marks import api, editor, review, shortcuts, ui, ux, viewport

OUT = ROOT / "artifacts"
blender_agent_marks.register()
bpy.context.preferences.view.show_splash = False
checks = []
scene = bpy.context.scene
cube = scene.objects["Cube"]
cube.data.calc_loop_triangles()
triangle = cube.data.loop_triangles[0]
point = sum((cube.data.vertices[i].co for i in triangle.vertices), Vector()) / 3
records = [api.create(scene, cube.name, triangle.index, point, f"Note {i}") for i in range(3)]
ids = [record["id"] for record in records]
# Review the second then first, so deleting the first must not block withdrawal
# of the second's earlier decision.
for index in (1, 0):
    record = records[index]
    review.submit_changes(
        [
            {
                "scene_name": scene.name,
                "marker_id": record["id"],
                "expected_revision": record["revision"],
                "summary": "Adjusted surface",
            }
        ]
    )
    review.decide(scene, record["id"], 2, "APPROVE")
api.document(scene).asm_active_index = 0
draft = editor.create_draft(api.get_mark(scene, ids[0]), note="Unconfirmed typing")
draft_name = draft.name


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)


def model_snapshot():
    return [
        (
            obj.name,
            [list(row) for row in obj.matrix_world],
            [list(vertex.co) for vertex in obj.data.vertices] if obj.type == "MESH" else None,
            obj.select_get(),
        )
        for obj in scene.objects
    ]


def key(event_type, **modifiers):
    for value in ("PRESS", "RELEASE"):
        window.event_simulate(
            type=event_type, value=value, x=region.x + 220, y=region.y + 220, **modifiers
        )


def delete_key():
    key("X", ctrl=True, alt=True, shift=True)


def call(operator, **arguments):
    with bpy.context.temp_override(window=window, area=area, region=region):
        return operator("EXEC_DEFAULT", True, **arguments)


def can_delete():
    with bpy.context.temp_override(window=window, area=area, region=region):
        return bpy.ops.asm.delete.poll()


def expect_error(name, code, operation):
    try:
        operation()
    except api.MarkError as exc:
        check(name, exc.code == code)
    else:
        raise AssertionError(name)


def steps():
    check("delete_shortcut_has_no_conflict", not shortcuts.conflicts(wm, "X"))
    check(
        "delete_binding_is_scoped_to_view3d",
        [
            (km.name, item.type, item.ctrl, item.alt, item.shift)
            for km, item in ui._keymaps
            if item.idname == "asm.delete"
        ]
        == [("3D View", "X", 1, 1, 1)],
    )
    before = [api.serialize(scene, mark) for mark in api.marks(scene)]
    history_before = review.history(scene)
    model_before = model_snapshot()
    number_before = api.document(scene).asm_next_number
    expect_error("stale_delete_refused", "REVISION_CONFLICT", lambda: api.delete(scene, ids[0], 1))
    expect_error("missing_delete_refused", "NOT_FOUND", lambda: api.delete(scene, "missing", 1))
    api.document(scene).asm_review_history = "[null]"
    expect_error(
        "invalid_history_refused_before_delete",
        "CORRUPT_REVIEW_HISTORY",
        lambda: api.delete(scene, ids[0], before[0]["revision"]),
    )
    check("failed_delete_is_atomic", [api.serialize(scene, m) for m in api.marks(scene)] == before)
    api.document(scene).asm_review_history = json.dumps(history_before)
    wm.asm_search = "No matching marker"
    check("filtered_out_active_marker_cannot_be_deleted", not can_delete())
    wm.asm_search = ""
    call(bpy.ops.ed.undo_push, message="Before annotation deletion")
    delete_key()
    yield 0.4
    check("shortcut_waits_for_confirmation", len(api.marks(scene)) == 3)
    key("ESC")
    yield 0.3
    check(
        "cancel_keeps_note_and_history",
        len(api.marks(scene)) == 3 and review.history(scene) == history_before,
    )
    delete_key()
    yield 0.3
    bpy.ops.screen.screenshot(filepath=str(OUT / "delete_confirmation_preview.png"))
    # Confirmation must stay tied to the displayed ID even if the list changes.
    api.document(scene).asm_active_index = 1
    key("RET")
    yield 0.6
    check("confirm_deletes_original_id_only", [m.marker_id for m in api.marks(scene)] == ids[1:])
    check("active_neighbor_keeps_identity", ux.active_mark(scene).marker_id == ids[1])
    check(
        "agent_read_immediately_omits_deleted_mark",
        api.get_surface_annotations(include_visibility=False)["total"] == 2,
    )
    check("only_deleted_mark_review_entries_removed", review.history(scene) == history_before[:1])
    check("model_and_selection_unchanged", model_snapshot() == model_before)
    check(
        "unconfirmed_draft_is_retained",
        bpy.data.texts[draft_name].as_string() == "Unconfirmed typing",
    )
    info = json.loads(bpy.data.texts[draft_name][editor.DRAFT_KEY])
    expect_error("retained_draft_cannot_resurrect_mark", "NOT_FOUND", lambda: editor.target(info))
    key("Z", ctrl=True)
    yield 0.7
    check(
        "undo_restores_complete_annotations",
        [api.serialize(scene, m) for m in api.marks(scene)] == before,
    )
    check("undo_restores_review_history", review.history(scene) == history_before)
    check("undo_restores_draft_target", editor.target(info)[1].marker_id == ids[0])
    key("Z", ctrl=True, shift=True)
    yield 0.7
    check("redo_deletes_same_mark", [m.marker_id for m in api.marks(scene)] == ids[1:])
    check("redo_preserves_model_and_selection", model_snapshot() == model_before)
    restored = review.withdraw(scene)
    check(
        "other_marker_review_can_still_be_withdrawn",
        restored["id"] == ids[1] and restored["status"] == "MODIFIED",
    )

    # A revision that changes after opening the confirmation must be retained.
    api.document(scene).asm_active_index = 0
    delete_key()
    yield 0.3
    mark = api.get_mark(scene, ids[1])
    api.update(scene, ids[1], mark.revision, note="Changed during confirmation")
    key("RET")
    yield 0.4
    check(
        "confirmation_refuses_newer_revision",
        len(api.marks(scene)) == 2
        and api.get_mark(scene, ids[1]).note == "Changed during confirmation",
    )

    # Deletion does not need a valid anchor, object selection or pending status.
    mark = api.get_mark(scene, ids[1])
    api.update(scene, ids[1], mark.revision, status="ARCHIVED")
    mark.anchor_json = "invalid anchor"
    check(
        "panel_delete_operator_accepts_archived_broken_anchor",
        call(bpy.ops.asm.delete) == {"FINISHED"},
    )
    check("last_neighbor_selected", ux.active_mark(scene).marker_id == ids[2])
    check("final_mark_can_be_deleted", call(bpy.ops.asm.delete) == {"FINISHED"})
    check(
        "empty_collection_has_no_active_or_delete",
        ux.active_mark(scene) is None and not can_delete(),
    )
    check(
        "empty_agent_read_is_clean",
        api.get_surface_annotations(include_visibility=False)["total"] == 0,
    )
    check(
        "deletion_never_reuses_marker_number", api.document(scene).asm_next_number == number_before
    )
    check("deleting_all_marks_keeps_model", model_snapshot() == model_before)


runner = steps()


def tick():
    global scene, wm, window, area, region
    try:
        scene = bpy.context.scene
        wm = bpy.context.window_manager
        window, area, region, _ = next(viewport.viewports(scene))
        return next(runner)
    except StopIteration:
        (OUT / "delete_test_report.json").write_text(
            json.dumps({"checks_passed": len(checks), "checks": checks}, indent=2), encoding="utf-8"
        )
    except Exception:
        (OUT / "delete_test_error.txt").write_text(
            traceback.format_exc() + "\n" + json.dumps(checks), encoding="utf-8"
        )
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(tick, first_interval=2)
