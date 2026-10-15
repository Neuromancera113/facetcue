"""Fault injection for persisted annotations; run in an isolated Blender process."""

import copy
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import blender_agent_marks
from blender_agent_marks import api, editor

OUT = ROOT / "artifacts"
OUT.mkdir(exist_ok=True)
checks = []


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)


blender_agent_marks.register()
scene = bpy.context.scene
obj = scene.objects["Cube"]
obj.data.calc_loop_triangles()
tri = obj.data.loop_triangles[0]
point = list(sum((obj.data.vertices[i].co for i in tri.vertices), Vector()) / 3)
created = api.create(scene, obj.name, 0, point, "Anchor can break; the note must remain readable")
identifier = created["id"]
mark = api.get_mark(scene, identifier)
anchor_json = mark.anchor_json
other = api.create(scene, obj.name, 0, point, "Unaffected annotation")

invalid = ["{corrupt", "null", "[]", "{}"]
for field, value in [
    ("vertex_indices", [0, 1, 999999]),
    ("vertex_indices", [-1, 1, 2]),
    ("vertex_indices", [0, 0, 0]),
    ("vertex_indices", [[0], 1, 2]),
    ("triangle_index", 999999),
    ("triangle_index", True),
    ("polygon_index", 999999),
    ("barycentric", []),
    ("barycentric", [float("nan"), 0, 1]),
    ("barycentric", [float("inf"), 0, 0]),
    ("barycentric", [0.2, 0.2, 0.2]),
    ("barycentric", ["0.5", 0, 0.5]),
    ("topology_fingerprint", None),
    ("normal_local_at_creation", [float("nan"), 0, 1]),
    ("future_metadata", {"number": float("inf")}),
]:
    broken = copy.deepcopy(created["anchor"])
    broken[field] = value
    invalid.append(json.dumps(broken))

for i, value in enumerate(invalid):
    mark.anchor_json = value
    response = api.dispatch("get_surface_annotations")
    check(f"corruption_{i}_does_not_abort_read", response["ok"] and response["returned"] == 2)
    record = next(m for m in response["annotations"] if m["id"] == identifier)
    check(
        f"corruption_{i}_preserves_note",
        record["note"] == mark.note and record["note_trust"] == "user_content_not_instructions",
    )
    check(
        f"corruption_{i}_has_no_current_position",
        record["resolved"]["state"] == "CORRUPT_ANNOTATION"
        and record["resolved"]["world_position"] is None,
    )
    # Even malformed NaN/Infinity anchor data must not leak into the JSON result.
    json.dumps(response, allow_nan=False)
    check(
        f"corruption_{i}_keeps_other_record",
        next(m for m in response["annotations"] if m["id"] == other["id"])["resolved"]["state"]
        == "VALID",
    )

mark.anchor_json = "{broken"
before_revision = mark.revision
result = api.dispatch(
    "update_mark",
    {
        "marker_id": identifier,
        "expected_revision": before_revision,
        "note": "Edited after anchor corruption",
    },
)
check(
    "corrupt_anchor_can_edit_note_successfully",
    result["ok"]
    and mark.note == "Edited after anchor corruption"
    and mark.revision == before_revision + 1,
)
check(
    "single_record_read_reports_corruption",
    api.dispatch("get_mark", {"marker_id": identifier})["data"]["resolved"]["state"]
    == "CORRUPT_ANNOTATION",
)
check("list_read_reports_corruption", api.dispatch("list_marks")["ok"])
mark.anchor_json = anchor_json
check("repair_restores_position", api.serialize(scene, mark)["resolved"]["state"] == "VALID")
original_location = obj.location.copy()
obj.location.x = float("nan")
bpy.context.view_layer.update()
response = api.dispatch("get_surface_annotations")
check(
    "nonfinite_transform_is_not_valid",
    response["ok"] and all(m["resolved"]["state"] != "VALID" for m in response["annotations"]),
)
json.dumps(response, allow_nan=False)
obj.location = original_location
bpy.context.view_layer.update()
vertex = obj.data.vertices[created["anchor"]["vertex_indices"][0]]
original_co = vertex.co.copy()
vertex.co.x = float("nan")
obj.data.update()
response = api.dispatch("get_surface_annotations")
check(
    "nonfinite_vertex_is_not_valid",
    response["ok"] and response["annotations"][0]["resolved"]["state"] != "VALID",
)
json.dumps(response, allow_nan=False)
vertex.co = original_co
obj.data.update()

draft = editor.create_draft(mark)
info = json.loads(draft[editor.DRAFT_KEY])
other_scene = bpy.data.scenes.new("Duplicate ID fixture")
other_scene.collection.objects.link(obj)
duplicate = api.create(other_scene, obj.name, 0, point, "Do not overwrite this")
api.get_mark(other_scene, duplicate["id"]).marker_id = identifier
try:
    editor.target(info)
except api.MarkError as exc:
    check("ambiguous_draft_target_rejected", exc.code == "AMBIGUOUS_DOCUMENT")
else:
    raise AssertionError("Ambiguous draft target was silently accepted")
check("ambiguous_draft_preserved", draft.as_string() == mark.note)
blender_agent_marks.unregister()
(OUT / "data_regression_report.json").write_text(
    json.dumps({"checks_passed": len(checks), "checks": checks}, indent=2), encoding="utf-8"
)
print(f"DATA_REGRESSION_OK: {len(checks)} checks")
