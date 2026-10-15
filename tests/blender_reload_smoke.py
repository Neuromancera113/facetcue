"""Preserve annotation metadata, drafts and review history across reload and save."""

import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import blender_agent_marks
from blender_agent_marks import api, connection, editor, review, spatial, ux, viewport

OUT = ROOT / "artifacts"
checks = []


def check(name, condition):
    assert condition, name
    checks.append(name)


blender_agent_marks.register()
scene = bpy.context.scene
obj = scene.objects["Cube"]
obj.data.calc_loop_triangles()
point = sum((obj.data.vertices[i].co for i in obj.data.loop_triangles[0].vertices), Vector()) / 3
records = [api.create(scene, obj.name, 0, point, f"Preserve note {i}") for i in range(4)]
for record, status in zip(records, ("OPEN", "IN_PROGRESS", "RESOLVED", "ARCHIVED")):
    api.update(scene, record["id"], record["revision"], status=status)
old = api.get_mark(scene, records[0]["id"])
check("review_summary_defaults_empty", old.change_summary == "")
review.submit_changes(
    [
        {
            "scene_name": scene.name,
            "marker_id": old.marker_id,
            "expected_revision": old.revision,
            "summary": "A model change is ready",
        }
    ]
)
review.decide(scene, old.marker_id, old.revision, "REJECT", "Revised request")
draft = editor.create_draft(api.get_mark(scene, records[1]["id"]))
draft_name, draft_body = draft.name, draft.as_string()
before = [api.serialize(scene, mark) for mark in api.marks(scene)]
history_before = review.history(scene)
registry_name = api.document(scene).name
api.geometry(obj, ux.GEOMETRY_CACHE)
spatial.get_index(
    viewport.ViewportContext(SimpleNamespace(view_layer=bpy.context.view_layer), None, None, None)
)
descriptor = connection._server.path
blender_agent_marks.unregister()
check(
    "disable_releases_geometry_and_spatial_caches", not ux.GEOMETRY_CACHE and not spatial._indexes
)
check("disable_removes_connection_descriptor", not descriptor.exists())
for name in (
    "core",
    "protocol",
    "runtime",
    "api",
    "spatial",
    "viewport",
    "ux",
    "review",
    "shortcuts",
    "compact",
    "floating",
    "editor",
    "connection",
    "ui",
):
    importlib.reload(importlib.import_module(f"blender_agent_marks.{name}"))
importlib.reload(blender_agent_marks)
blender_agent_marks.register()
check(
    "full_reload_preserves_all_annotation_fields",
    before == [api.serialize(scene, m) for m in api.marks(scene)],
)
check("full_reload_preserves_review_history", review.history(scene) == history_before)
check("full_reload_preserves_draft", bpy.data.texts[draft_name].as_string() == draft_body)
check("full_reload_preserves_registry_identity", api.document(scene).name == registry_name)
path = str(OUT / "review_reload.blend")
bpy.ops.wm.save_as_mainfile(filepath=path)
bpy.ops.wm.open_mainfile(filepath=path)
scene = bpy.context.scene
check(
    "save_reload_preserves_all_annotation_fields",
    before == [api.serialize(scene, m) for m in api.marks(scene)],
)
check("save_reload_preserves_review_history", review.history(scene) == history_before)
review.withdraw(scene)
restored = api.get_mark(scene, records[0]["id"])
check(
    "withdraw_after_reload_restores_pending_review",
    restored.note == records[0]["note"] and restored.status == "MODIFIED",
)
check(
    "withdraw_preserves_change_summary_and_base_color",
    restored.change_summary == "A model change is ready"
    and list(restored.color) == records[0]["color_rgba"],
)
blender_agent_marks.unregister()
(OUT / "reload_test_report.json").write_text(
    json.dumps({"checks_passed": len(checks), "checks": checks}, indent=2), encoding="utf-8"
)
print(f"RELOAD_OK: {len(checks)} checks")
