"""Headless spatial query correctness and incremental invalidation regression."""

import gc
import json
import random
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import blender_agent_marks
from blender_agent_marks import spatial, ux, viewport

blender_agent_marks.register()
scene = bpy.context.scene
view = viewport.ViewportContext(
    SimpleNamespace(view_layer=bpy.context.view_layer), None, None, None
)
cube = scene.objects["Cube"]
checks = []
timings = {}


def check(name, condition):
    assert condition, name
    checks.append(name)


def compare(name, origin=(0.2, 0.1, 5), direction=(0, 0, -1), limit=100):
    origin, direction = Vector(origin), Vector(direction).normalized()
    index = spatial.get_index(view)
    fast = index.query(view, origin, direction, limit)
    slow = viewport.nearest_hit_conservative(scene, view, origin, direction, limit)
    check(
        name,
        (fast is None and slow is None)
        or (
            fast is not None
            and slow is not None
            and fast.obj == slow.obj
            and fast.is_instance == slow.is_instance
            and fast.reason == slow.reason
            and (fast.point_world - slow.point_world).length < 1e-4
        ),
    )
    return fast


def update():
    bpy.context.view_layer.update()


for i in range(4096):
    obj = bpy.data.objects.new(f"Surrounding mesh {i}", cube.data)
    scene.collection.objects.link(obj)
    obj.location = (8 + 2.5 * (i % 32), 2.5 * (i // 32), 0)
update()
start = time.perf_counter()
index = spatial.get_index(view)
timings["initial_build_ms"] = (time.perf_counter() - start) * 1000
compare("large_scene_front_surface")
cube.show_in_front = True
check(
    "cached_candidates_recheck_display_flags",
    compare("flag_without_update", limit=1).reason == "in_front_geometry",
)
cube.show_in_front = False
check("cleared_flag_not_cached", compare("clear_flag_without_update", limit=1) is None)
start = time.perf_counter()
for _ in range(100):
    index.query(view, Vector((0.2, 0.1, 5)), Vector((0, 0, -1)), 100)
timings["warm_query_mean_ms"] = (time.perf_counter() - start) * 10
for i in range(130):
    index.query(view, Vector((0.2 + i * 0.01, 0.1, 5)), Vector((0, 0, -1)), 100)
check("candidate_cache_stays_bounded_during_navigation", len(index.candidate_cache) <= 64)

rng = random.Random(6842)
for i in range(24):
    compare(f"random_ray_{i}", (rng.uniform(-5, 100), rng.uniform(-5, 330), 8), (0.02, -0.03, -1))

before_root = index.root
cube.select_set(False)
update()
start = time.perf_counter()
index = spatial.get_index(view)
timings["selection_refresh_ms"] = (time.perf_counter() - start) * 1000
check("selection_keeps_existing_spatial_tree", index.root is before_root)

cube.location.x = -4
update()
start = time.perf_counter()
index = spatial.get_index(view)
timings["single_transform_refresh_ms"] = (time.perf_counter() - start) * 1000
check("single_transform_refits_existing_tree", index.root is before_root)
check("moved_surface_not_left_in_old_position", compare("transform_correctness") is None)
cube.location.x = 0
cube.scale = (-1.5, 0.5, 1.2)
cube.rotation_euler = (0.1, 0.2, 0.3)
update()
compare("negative_nonuniform_rotated_transform")

cube.location.z = -5
cube.show_in_front = True
update()
check(
    "in_front_can_exceed_requested_distance",
    compare("in_front", limit=2).reason == "in_front_geometry",
)
cube.show_in_front = False
cube.location.z = 0
cube.display_type = "WIRE"
update()
check("wire_is_explicitly_ambiguous", compare("wire").reason == "wire_or_bounds_geometry")
cube.display_type = "SOLID"
cube.hide_set(True)
update()
check("hidden_object_ignored", compare("hide") is None)
cube.hide_set(False)
update()
compare("unhidden_object_reappears")

cube.data = cube.data.copy()
for vertex in cube.data.vertices:
    vertex.co.x -= 3
cube.data.update()
update()
check("deformed_surface_not_cached", compare("mesh_deformation") is None)
cube.data = bpy.data.meshes["Cube"]
cube.matrix_world.identity()
modifier = cube.modifiers.new("Changed evaluated shape", "SOLIDIFY")
modifier.thickness = 0.2
update()
compare("evaluated_mesh_modifier")
cube.modifiers.remove(modifier)

curve_data = bpy.data.curves.new("Generated surface", "CURVE")
curve_data.dimensions = "2D"
curve_data.fill_mode = "BOTH"
spline = curve_data.splines.new("POLY")
spline.points.add(3)
for point, coordinate in zip(
    spline.points, ((-1, -1, 0, 1), (1, -1, 0, 1), (1, 1, 0, 1), (-1, 1, 0, 1))
):
    point.co = coordinate
spline.use_cyclic_u = True
curve = bpy.data.objects.new("Curve blocker", curve_data)
scene.collection.objects.link(curve)
curve.location.z = 2
update()
check("curve_blocks_mesh", compare("curve").obj == curve)
for point in spline.points:
    point.co.x += 4
update()
check("curve_deformation_rebuilds_only_its_surface", compare("curve_deformation").obj == cube)
bpy.data.objects.remove(curve, do_unlink=True)
compare("direct_removal_before_depsgraph_notification")
update()
compare("deleted_curve_not_retained")

source = bpy.data.collections.new("Instance source")
source.objects.link(bpy.data.objects.new("Instance mesh", cube.data))
instancer = bpy.data.objects.new("Actual instance", None)
scene.collection.objects.link(instancer)
instancer.instance_type = "COLLECTION"
instancer.instance_collection = source
instancer.location.z = 2
update()
check("true_instances_keep_conservative_path", not spatial.get_index(view).supported)
origin, direction = Vector((0.2, 0.1, 5)), Vector((0, 0, -1))
space = next(
    area.spaces.active
    for screen in bpy.data.screens
    for area in screen.areas
    if area.type == "VIEW_3D"
)
hit = viewport.nearest_hit(scene, view._replace(space=space), origin, direction)
check(
    "fallback_retains_instancer_ownership",
    hit.is_instance
    and hit.obj.name == "Instance mesh"
    and (hit.point_world - Vector((0.2, 0.1, 3))).length < 1e-4,
)
bpy.data.objects.remove(instancer, do_unlink=True)
update()
check("removing_instance_restores_spatial_path", spatial.get_index(view).supported)
compare("after_instance_removal")

# Exercise deletion before notifications repeatedly, including Python GC and
# changing identities; stale evaluated wrappers must not survive a rebuild.
for i in range(12):
    transient = bpy.data.objects.new(f"Transient blocker {i}", cube.data)
    scene.collection.objects.link(transient)
    transient.location.z = 2
    update()
    check(f"transient_blocks_{i}", compare(f"before_direct_delete_{i}").obj == transient)
    transient.name = f"Renamed blocker {i}"
    check(f"rename_keeps_surface_{i}", compare(f"rename_{i}").obj == transient)
    bpy.data.objects.remove(transient, do_unlink=True)
    check(f"deleted_surface_not_used_{i}", compare(f"after_direct_delete_{i}").obj == cube)
    gc.collect()
    compare(f"after_gc_{i}")

ux.invalidate()
check("undo_load_manual_invalidation_drops_rna_indexes", not spatial._indexes)
compare("after_full_invalidation")
(ROOT / "artifacts" / "spatial_test_report.json").write_text(
    json.dumps({"checks_passed": len(checks), "checks": checks, "timings": timings}, indent=2),
    encoding="utf8",
)
