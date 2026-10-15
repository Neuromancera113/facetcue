"""Viewport-specific projection and conservative opaque-mesh visibility."""

import math
from collections.abc import Iterator
from typing import NamedTuple

import bpy
from mathutils import Vector

from .core import MarkError

XRAY_OCCLUDED_OPACITY = 0.4  # 60% transparent; shared by marker, label and badge.


class ViewportContext(NamedTuple):
    """Session-local RNA references; reacquire after load, Undo or area changes."""

    window: bpy.types.Window
    area: bpy.types.Area
    region: bpy.types.Region
    space: bpy.types.SpaceView3D


def viewports(scene: bpy.types.Scene) -> Iterator[ViewportContext]:
    for window in bpy.context.window_manager.windows:
        if window.scene != scene:
            continue
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                for region in area.regions:
                    if region.type == "WINDOW":
                        yield ViewportContext(window, area, region, area.spaces.active)


def viewport_id(view):
    window, area, region, _ = view
    return f"{window.as_pointer():x}:{area.as_pointer():x}:{region.as_pointer():x}"


def list_viewports(scene):
    return [
        {
            "viewport_id": viewport_id(view),
            "width": view.region.width,
            "height": view.region.height,
            "window_region_origin": [view.region.x, view.region.y],
            "pixel_origin": "bottom_left",
            "view_layer": view.window.view_layer.name,
            "shading": view.space.shading.type,
            "view_matrix": [list(row) for row in view.space.region_3d.view_matrix],
            "view_projection_matrix": [
                list(row) for row in view.space.region_3d.perspective_matrix
            ],
        }
        for view in viewports(scene)
    ]


def find_viewport(scene, identifier):
    for view in viewports(scene):
        if viewport_id(view) == identifier:
            return view
    raise MarkError("VIEWPORT_NOT_FOUND", "Viewport IDs are session-local; list viewports again")


def support_reason(scene, view):
    window, _, _, space = view
    if space.region_quadviews:
        return "quad_view_not_supported"
    if space.shading.type != "SOLID":
        return "requires_solid_view"
    if space.region_3d.use_clip_planes:
        return "custom_clip_planes_not_supported"
    return None


def is_xray(space):
    return (
        space.shading.type == "SOLID"
        and space.shading.show_xray
        or space.shading.type == "WIREFRAME"
        and space.shading.show_xray_wireframe
    )


def with_overlay(data, mark, space):
    from .ux import matches

    manager = bpy.context.window_manager
    data["surface_visibility"] = data["state"]
    data["display_opacity"] = 1.0
    if is_xray(space):
        if data["state"] == "OCCLUDED":
            data["display_opacity"] = XRAY_OCCLUDED_OPACITY
        data["state"] = "XRAY"
    data["overlay_drawn"] = bool(
        data["state"] in {"VISIBLE", "XRAY"}
        and manager.asm_show_overlay
        and space.overlay.show_overlays
        and mark.status != "ARCHIVED"
        and matches(mark, manager)
    )
    return data


def ray_from_pixel(view, x, y):
    """Unproject in view space, avoiding a distant world-space far-plane point.

    Inverting projection * view and subtracting near/far world positions loses
    float precision as the view rotates, especially with a large clip range.
    Construct the direction before applying the view transform instead.
    """
    _, _, region, space = view
    region_3d = space.region_3d
    inverse_projection = region_3d.window_matrix.inverted()
    inverse_view = region_3d.view_matrix.inverted()
    ndc_x, ndc_y = 2 * x / region.width - 1, 2 * y / region.height - 1
    near_view = inverse_projection @ Vector((ndc_x, ndc_y, -1, 1))
    near_view = near_view.xyz / near_view.w
    direction_view = near_view.normalized() if region_3d.is_perspective else Vector((0, 0, -1))
    origin_world = inverse_view @ near_view
    direction_world = (inverse_view.to_3x3() @ direction_view).normalized()
    return origin_world, direction_world


class SurfaceHit(NamedTuple):
    """Ray result in object-local and world coordinates, measured in Blender units.

    obj is the original object. polygon_index addresses the evaluated ray-cast
    mesh; callers must validate attachment support before treating it as a base
    mesh index. This result is not a persisted annotation or a public wire format.
    """

    obj: bpy.types.Object
    point_local: Vector
    polygon_index: int
    point_world: Vector
    distance_world: float
    is_instance: bool = False
    reason: str | None = None


def ray_box(origin, direction, bounds, limit=float("inf")):
    """Slab test; direction is local displacement per WORLD distance unit."""
    near, far = 0.0, limit
    for axis in range(3):
        lo, hi = bounds[axis]
        if abs(direction[axis]) < 1e-15:
            if origin[axis] < lo or origin[axis] > hi:
                return None
        else:
            a = (lo - origin[axis]) / direction[axis]
            b = (hi - origin[axis]) / direction[axis]
            near, far = max(near, min(a, b)), min(far, max(a, b))
            if near > far:
                return None
    return near


def ray_candidates(view):
    window, _, _, space = view
    depsgraph = window.view_layer.depsgraph
    # Curves and text may appear here as generated Mesh instances in Blender 5.2.
    # Their evaluated mesh is an occluder, not a reason to reject the whole scene.
    for instance in depsgraph.object_instances:
        obj = instance.object
        if not instance.show_self or obj.type not in {"MESH", "VOLUME", "POINTCLOUD"}:
            continue
        matrix = instance.matrix_world.copy()
        if abs(matrix.to_3x3().determinant()) < 1e-12:
            continue
        inverse = matrix.inverted()
        bounds = tuple(
            (min(v[a] for v in obj.bound_box) - 1e-5, max(v[a] for v in obj.bound_box) + 1e-5)
            for a in range(3)
        )
        original = obj.original
        parent = instance.parent.original if instance.is_instance and instance.parent else original
        # Generated evaluated objects can be reused by the iterator. Consume each
        # one before advancing; never keep these RNA references in a cache/list.
        yield obj, original, parent, matrix, inverse, bounds, instance.is_instance


def begin_query_batch(cache):
    """Keep geometry caches, but never carry display/visibility state across redraws."""
    for key in list(cache):
        if isinstance(key, tuple) and key[0] == "ray_result":
            del cache[key]


def nearest_hit(scene, view, origin, direction, distance=float("inf"), cache=None):
    from .spatial import get_index

    window, _, _, space = view
    if cache is None:
        cache = {}
    key = (
        "ray_result",
        window.view_layer.as_pointer(),
        space.as_pointer(),
        space.local_view.as_pointer() if space.local_view else 0,
        tuple(origin),
        tuple(direction),
        distance,
    )
    if key in cache:
        return cache[key]
    index = get_index(view)
    if index.supported:
        closest = index.query(view, origin, direction, distance)
    else:
        closest = nearest_hit_conservative(scene, view, origin, direction, distance)
    keys = [k for k in cache if isinstance(k, tuple) and k[0] == "ray_result"]
    if len(keys) >= 128:
        for old in keys[:64]:
            del cache[old]
    cache[key] = closest
    return closest


def nearest_hit_conservative(scene, view, origin, direction, distance=float("inf")):
    window, _, _, space = view
    closest = None
    for evaluated, obj, owner, matrix, inverse, bounds, is_instance in ray_candidates(view):
        # For collection/geometry instances, visibility belongs to the instancer.
        if not owner.visible_get(view_layer=window.view_layer, viewport=space):
            continue
        local_origin = inverse @ origin
        local_vector = inverse.to_3x3() @ direction
        special = obj.show_in_front or owner.show_in_front
        limit = float("inf") if special else distance
        travel = ray_box(local_origin, local_vector, bounds, limit)
        if travel is None:
            continue
        reason = None
        if obj.display_type in {"WIRE", "BOUNDS"}:
            reason = "wire_or_bounds_geometry"
        elif evaluated.type != "MESH":
            reason = "non_surface_geometry"
        if reason:
            # Ambiguous visual shapes only matter when this ray crosses their bounds.
            point, face = local_origin + local_vector * travel, -1
        else:
            length = local_vector.length
            local_limit = min(limit * length, 1e30) if math.isfinite(limit) else 1e30
            hit, point, _, face = evaluated.ray_cast(
                local_origin,
                local_vector / length,
                distance=local_limit,
                depsgraph=window.view_layer.depsgraph,
            )
            if not hit:
                continue
        world = matrix @ point
        travel = (world - origin).dot(direction)
        if travel < 0:
            continue
        if special:
            return SurfaceHit(obj, point, face, world, travel, is_instance, "in_front_geometry")
        if travel <= distance:
            distance = travel
            closest = SurfaceHit(obj, point, face, world, travel, is_instance, reason)
    return closest


def edit_mode_present(scene, cache=None):
    key = ("edit_mode", scene.as_pointer())
    if cache is not None and key in cache:
        return cache[key]
    result = any(obj.mode != "OBJECT" for obj in scene.objects if obj.type == "MESH")
    if cache is not None:
        cache[key] = result
    return result


def visibility(scene, mark, resolved, view, cache=None):
    window, _, region, space = view
    data = {
        "viewport_id": viewport_id(view),
        "state": "UNKNOWN",
        "screen_px": None,
        "screen_uv_top_left": None,
        "overlay_drawn": False,
        "method": "evaluated_surface_raycast",
        "pixel_origin": "bottom_left",
        "region_size": [region.width, region.height],
    }
    if resolved["state"] != "VALID":
        data.update(state="ANCHOR_INVALID", reason=resolved["state"])
        return data
    if not mark.target.visible_get(view_layer=window.view_layer, viewport=space):
        data["state"] = "OBJECT_HIDDEN"
        return data
    point = Vector(resolved["world_position"])
    clip = space.region_3d.perspective_matrix @ point.to_4d()
    if clip.w <= 0:
        data["state"] = "BEHIND_VIEW"
        return data
    ndc = clip.xyz / clip.w
    x, y = (ndc.x + 1) * region.width / 2, (ndc.y + 1) * region.height / 2
    data.update(screen_px=[x, y], screen_uv_top_left=[(ndc.x + 1) / 2, (1 - ndc.y) / 2])
    if not -1 <= ndc.z <= 1:
        data["state"] = "CLIPPED"
        return data
    if not (0 <= x < region.width and 0 <= y < region.height):
        data["state"] = "OFFSCREEN"
        return data
    reason = support_reason(scene, view)
    if reason:
        data["reason"] = reason
        return with_overlay(data, mark, space) if is_xray(space) else data
    if edit_mode_present(scene, cache):
        data["reason"] = "edit_mode_geometry_present"
        return with_overlay(data, mark, space) if is_xray(space) else data
    origin, _ = ray_from_pixel(view, x, y)
    # The anchor position is already known. Aim at it directly instead of
    # requiring a world -> screen -> world round trip to reproduce it exactly.
    # Keep the near-plane origin so clipped foreground geometry stays excluded.
    direction = (point - origin).normalized()
    distance = (point - origin).length
    hit = nearest_hit(scene, view, origin, direction, distance + max(1e-5, distance * 1e-5), cache)
    tolerance = max(1e-5, distance * 1e-5)
    if hit is None:
        data["reason"] = "surface_not_confirmed"
    elif hit.reason:
        data["reason"] = hit.reason
    elif (
        hit.obj == mark.target
        and not hit.is_instance
        and (hit.point_world - point).length <= tolerance
    ):
        data["state"] = "VISIBLE"
    else:
        data["state"] = "OCCLUDED"
    return with_overlay(data, mark, space)


def pick_surface(scene, view, x, y):
    """Resolve a click without creating data: cancelling the note dialog stays clean."""
    from .api import geometry
    from .core import barycentric

    _, _, region, space = view
    reason = support_reason(scene, view)
    if reason:
        raise MarkError("UNSUPPORTED_VIEW", reason)
    if any(obj.mode != "OBJECT" for obj in scene.objects if obj.type == "MESH"):
        raise MarkError("EDIT_MODE", "Leave mesh Edit Mode before placing a mark")
    if not (0 <= x < region.width and 0 <= y < region.height):
        raise MarkError("OUTSIDE_VIEW", "Click inside the viewport")
    origin, direction = ray_from_pixel(view, x, y)
    hit = nearest_hit(scene, view, origin, direction)
    if hit is None:
        raise MarkError("NO_SURFACE", "No visible mesh surface was hit")
    obj, point_local, polygon_index = hit.obj, hit.point_local, hit.polygon_index
    if hit.reason:
        raise MarkError("UNSUPPORTED_TARGET", f"{hit.reason}|{obj.name}")
    if obj.type != "MESH":
        raise MarkError("NON_MESH_TARGET", obj.name)
    if hit.is_instance:
        raise MarkError("INSTANCE_TARGET", obj.name)
    clip = space.region_3d.perspective_matrix @ hit.point_world.to_4d()
    if clip.w <= 0 or not -1 <= clip.z / clip.w <= 1:
        raise MarkError("NO_SURFACE", "Hit is outside the viewport clipping range")
    mesh, signature = geometry(obj)
    for tri in mesh.loop_triangles:
        if tri.polygon_index == polygon_index:
            try:
                vertices = [mesh.vertices[i].co for i in tri.vertices]
                # Blender ray_cast uses float precision; a long orthographic ray
                # can land a few ulps off the face plane. Project that small error
                # onto the known hit face before applying strict barycentric bounds.
                normal = (vertices[1] - vertices[0]).cross(vertices[2] - vertices[0]).normalized()
                deviation = (point_local - vertices[0]).dot(normal)
                inverse_scale = max(row.length for row in obj.matrix_world.inverted().to_3x3())
                tolerance = max(1e-6, hit.distance_world * inverse_scale * 2e-7)
                if abs(deviation) > tolerance:
                    continue
                projected_local = point_local - normal * deviation
                barycentric(projected_local, *vertices)
                return obj, tri.index, projected_local, signature
            except MarkError as exc:
                if exc.code not in {"POINT_OUTSIDE_TRIANGLE", "DEGENERATE_TRIANGLE"}:
                    raise
    raise MarkError("NO_TRIANGLE", "Hit face could not be mapped to a triangle")


def create_at_pixel(scene, view, x, y, note):
    from .api import create

    obj, index, point, _ = pick_surface(scene, view, x, y)
    return create(scene, obj.name, index, point, note)


def focus_mark(scene, mark, view=None):
    """Move only the viewport. Preserve object selection and camera transforms."""
    from .api import load_anchor, resolve

    try:
        resolved = resolve(scene, mark)
    except MarkError as exc:
        if exc.code not in {
            "STALE_TOPOLOGY",
            "MESH_REPLACED",
            "UNSUPPORTED_GEOMETRY",
            "DEGENERATE_TRIANGLE",
        }:
            raise
        # Review remains navigable after topology edits. This is explicitly an
        # original anchor location, not a claim that the new surface is attached.
        anchor = load_anchor(mark)
        if not mark.target:
            raise
        from .core import vector3

        point_local = Vector(vector3(anchor["local_position_at_creation"]))
        normal_local = Vector(vector3(anchor["normal_local_at_creation"]))
        matrix = mark.target.matrix_world
        resolved = {
            "world_position": matrix @ point_local,
            "normal_world": (matrix.to_3x3().inverted().transposed() @ normal_local).normalized(),
        }
    if bpy.app.background:
        raise MarkError("NO_VIEWPORT", "Open a 3D viewport to focus this mark")
    if view is None:
        views = list(viewports(scene))
        preferred = [view for view in views if view.area == bpy.context.area]
        view = (
            preferred[0]
            if preferred
            else max(views, key=lambda v: v.region.width * v.region.height, default=None)
        )
    if view is None:
        raise MarkError("NO_VIEWPORT", "Open a 3D viewport to focus this mark")
    window, area, _, space = view
    if space.region_quadviews:
        raise MarkError("UNSUPPORTED_VIEW", "quad_view_not_supported")
    if not mark.target.visible_get(view_layer=window.view_layer, viewport=space):
        raise MarkError("OBJECT_HIDDEN", "Unhide the target object before focusing")
    rv3d = space.region_3d
    if rv3d.view_perspective == "CAMERA":
        rv3d.view_perspective = "PERSP"
    rv3d.view_location = resolved["world_position"]
    rv3d.view_rotation = Vector(resolved["normal_world"]).to_track_quat("Z", "Y")
    # view_location is Blender's orbit pivot. Frame a local patch, not the whole
    # object; changing this view never changes the active object or camera data.
    rv3d.view_distance = max(max(mark.target.dimensions) * 0.6, 0.1, space.clip_start * 10)
    area.tag_redraw()
    return viewport_id(view)
