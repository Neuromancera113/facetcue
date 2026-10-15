"""Run only in an isolated Blender --background --factory-startup process."""

import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import blender_agent_marks
from blender_agent_marks import api

OUT = ROOT / "artifacts"
OUT.mkdir(exist_ok=True)
checks = []


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)


blender_agent_marks.register()
scene = bpy.context.scene
text_count = len(bpy.data.texts)
check(
    "empty_read_creates_no_registry",
    api.dispatch("list_marks")["data"] == [] and len(bpy.data.texts) == text_count,
)
obj = bpy.data.objects.get("Cube")
mesh = obj.data
mesh.calc_loop_triangles()
tri = mesh.loop_triangles[0]
point = sum((mesh.vertices[i].co for i in tri.vertices), Vector()) / 3
counts_before = (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.materials))
r = api.dispatch(
    "create_mark",
    {
        "object_name": obj.name,
        "triangle_index": 0,
        "local_position": list(point),
        "note": "这里改为圆角，保持外轮廓",
    },
)
check("create", r["ok"])
marker_id = r["data"]["id"]
mark = api.get_mark(scene, marker_id)
check(
    "no_annotation_geometry",
    counts_before == (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.materials)),
)
check("barycentric", all(abs(x - 1 / 3) < 1e-6 for x in r["data"]["anchor"]["barycentric"]))
obj.name = "RenamedTarget"
obj.location = (7, -2, 3)
obj.rotation_euler = (0.2, 0.4, 0.3)
obj.scale = (2, 3, 0.5)
bpy.context.view_layer.update()
resolved = api.serialize(scene, mark)["resolved"]
check("rename_preserves_target", mark.target == obj)
check(
    "nonuniform_transform_follows",
    (Vector(resolved["world_position"]) - obj.matrix_world @ point).length < 1e-5,
)
check("normal_normalized", abs(Vector(resolved["normal_world"]).length - 1) < 1e-6)
world_verts = [obj.matrix_world @ mesh.vertices[i].co for i in tri.vertices]
check(
    "normal_perpendicular",
    abs(Vector(resolved["normal_world"]).dot(world_verts[1] - world_verts[0])) < 1e-5,
)
bpy.context.window_manager.asm_show_overlay = False
check("hidden_overlay_still_readable", len(api.dispatch("list_marks")["data"]) == 1)
obj.hide_set(True)
check("hidden_object_still_readable", api.serialize(scene, mark)["resolved"]["state"] == "VALID")
obj.hide_set(False)
r = api.dispatch(
    "update_mark", {"marker_id": marker_id, "expected_revision": 1, "status": "IN_PROGRESS"}
)
check("revision_increment", r["ok"] and r["data"]["revision"] == 2)
r = api.dispatch(
    "update_mark", {"marker_id": marker_id, "expected_revision": 1, "note": "stale write"}
)
check("revision_conflict", not r["ok"] and r["error"]["code"] == "REVISION_CONFLICT")
check("conflict_no_mutation", mark.note == "这里改为圆角，保持外轮廓")
clone = obj.copy()
scene.collection.objects.link(clone)
check("duplicate_does_not_steal_anchor", mark.target == obj and mark.target != clone)
bpy.data.objects.remove(clone, do_unlink=True)
path = OUT / "smoke.blend"
bpy.ops.wm.save_as_mainfile(filepath=str(path))
bpy.ops.wm.open_mainfile(filepath=str(path))
scene = bpy.context.scene
mark = api.get_mark(scene, marker_id)
obj, mesh = mark.target, mark.target.data
check(
    "save_reload_note_and_pointer",
    mark.note == "这里改为圆角，保持外轮廓" and obj.name == "RenamedTarget",
)
check("save_reload_revision", mark.revision == 2)
check("save_reload_anchor", api.serialize(scene, mark)["resolved"]["state"] == "VALID")
replacement = mesh.copy()
obj.data = replacement
check(
    "mesh_replacement_detected", api.serialize(scene, mark)["resolved"]["state"] == "MESH_REPLACED"
)
obj.data = mesh
modifier = obj.modifiers.new("TopologyRisk", "SUBSURF")
check(
    "modifier_not_silently_mapped",
    api.serialize(scene, mark)["resolved"]["state"] == "UNSUPPORTED_GEOMETRY",
)
obj.modifiers.remove(modifier)
obj.scale.x = 0
bpy.context.view_layer.update()
check(
    "zero_scale_rejected", api.serialize(scene, mark)["resolved"]["state"] == "SINGULAR_TRANSFORM"
)
obj.scale.x = 2
bpy.context.view_layer.update()
# Modify connectivity while keeping polygon and vertex counts constant.
original_loop = mesh.loops[0].vertex_index
mesh.loops[0].vertex_index = (original_loop + 1) % len(mesh.vertices)
mesh.update()
check(
    "same_count_topology_change_detected",
    api.serialize(scene, mark)["resolved"]["state"] == "STALE_TOPOLOGY",
)
mesh.loops[0].vertex_index = original_loop
mesh.update()
check("topology_restored", api.serialize(scene, mark)["resolved"]["state"] == "VALID")
# Export a model with custom metadata enabled and verify no annotation text/geometry leaks.
obj.location = (0, 0, 0)
obj.rotation_euler = (0, 0, 0)
obj.scale = (1, 1, 1)
bpy.context.view_layer.update()
export_path = OUT / "smoke.obj"
bpy.ops.wm.obj_export(filepath=str(export_path), export_materials=False)
export_text = export_path.read_text(encoding="utf-8")
check("obj_no_note_text", mark.note not in export_text and marker_id not in export_text)
check(
    "obj_vertex_count",
    sum(line.startswith("v ") for line in export_text.splitlines()) == len(mesh.vertices),
)
# Probe glTF extras explicitly: scene metadata exporters need separate verification.
gltf_path = OUT / "smoke.gltf"
bpy.ops.export_scene.gltf(
    filepath=str(gltf_path), export_format="GLTF_SEPARATE", export_extras=True
)
gltf_text = gltf_path.read_text(encoding="utf-8")
check("gltf_extras_no_note_text", mark.note not in gltf_text and marker_id not in gltf_text)
# Workbench rendering ignores viewport draw handlers. Compare with and without records.
scene.render.engine = "BLENDER_WORKBENCH"
scene.render.resolution_x = scene.render.resolution_y = 64
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = str(OUT / "render_with_marks.png")
bpy.ops.render.render(write_still=True)
first_image = bpy.data.images.load(str(OUT / "render_with_marks.png"), check_existing=False)
first = list(first_image.pixels)
sample = api.dispatch("list_marks")
(OUT / "sample_response.json").write_text(
    json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8"
)
api.document(scene).asm_marks.clear()
scene.render.filepath = str(OUT / "render_without_marks.png")
bpy.ops.render.render(write_still=True)
second_image = bpy.data.images.load(str(OUT / "render_without_marks.png"), check_existing=False)
check("render_pixels_unchanged", first == list(second_image.pixels))
result = api.create(scene, obj.name, 0, list(point), "temporary orphan")
mark = api.get_mark(scene, result["id"])
bpy.data.objects.remove(obj, do_unlink=True)
check("deleted_object_orphaned", api.serialize(scene, mark)["resolved"]["state"] == "ORPHANED")
blender_agent_marks.unregister()
blender_agent_marks.register()
check("register_unregister_cycle", hasattr(bpy.types.Text, "asm_marks"))
check("reenable_preserves_note", api.marks(scene)[0].note == "temporary orphan")
blender_agent_marks.unregister()
report = {"blender": bpy.app.version_string, "checks_passed": len(checks), "checks": checks}
(OUT / "blender_test_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print("AGENT_MARKS_SMOKE_OK " + json.dumps(report))
