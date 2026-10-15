"""Incremental object broad phase. Evaluated instance RNA never survives iteration."""

import weakref

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

_indexes = {}
_INFINITY = float("inf")


def intersects(origin, inverse_direction, bounds):
    near, far = 0.0, _INFINITY
    for axis in range(3):
        lo, hi = bounds[axis]
        inv = inverse_direction[axis]
        if inv is None:
            if origin[axis] < lo or origin[axis] > hi:
                return False
            continue
        a, b = (lo - origin[axis]) * inv, (hi - origin[axis]) * inv
        if a > b:
            a, b = b, a
        if a > near:
            near = a
        if b < far:
            far = b
        if near > far:
            return False
    return True


class Entry:
    def __init__(self, instance, order, original):
        # Acquire from Main, not through the evaluated-instance RNA wrapper.
        self.original = original
        self.order = order
        self.is_instance = instance.is_instance
        self.tree = None
        self.leaf = None
        self.refresh(instance, geometry=True)

    def refresh(self, instance, *, geometry=False):
        if geometry:
            evaluated = instance.object
            obj = evaluated.original
            self.pointer = obj.as_pointer()
        self.matrix = instance.matrix_world.copy()
        self.inverse = self.matrix.inverted()
        if geometry:
            self.tree = None
            corners = tuple(tuple(corner) for corner in evaluated.bound_box)
            self.bounds = tuple(
                (min(v[a] for v in corners) - 1e-5, max(v[a] for v in corners) + 1e-5)
                for a in range(3)
            )
        corners = [
            self.matrix @ Vector((x, y, z))
            for x in self.bounds[0]
            for y in self.bounds[1]
            for z in self.bounds[2]
        ]
        self.world = tuple(
            (min(v[a] for v in corners), max(v[a] for v in corners)) for a in range(3)
        )

    def object(self):
        try:
            return self.original if self.original.as_pointer() == self.pointer else None
        except ReferenceError:
            return None


class Node:
    def __init__(self, entries, parent=None):
        # Weak back-links release RNA and curve BVHs immediately on eviction.
        self.parent = weakref.ref(parent) if parent else None
        self.entries = None
        self.children = None
        self.bounds = self.union(e.world for e in entries)
        if len(entries) <= 6:
            self.entries = entries
            for entry in entries:
                entry.leaf = weakref.ref(self)
        else:
            axis = max(range(3), key=lambda a: self.bounds[a][1] - self.bounds[a][0])
            ordered = sorted(entries, key=lambda e: e.world[axis][0] + e.world[axis][1])
            middle = len(ordered) // 2
            self.children = Node(ordered[:middle], self), Node(ordered[middle:], self)

    @staticmethod
    def union(boxes):
        boxes = list(boxes)
        return tuple((min(b[a][0] for b in boxes), max(b[a][1] for b in boxes)) for a in range(3))

    def refit(self):
        self.bounds = self.union(
            (e.world for e in self.entries)
            if self.entries is not None
            else (child.bounds for child in self.children)
        )
        if self.parent:
            parent = self.parent()
            if parent:
                parent.refit()

    def candidates(self, origin, inverse_direction):
        pending = [self]
        while pending:
            node = pending.pop()
            if not intersects(origin, inverse_direction, node.bounds):
                continue
            if node.entries is not None:
                for entry in node.entries:
                    if intersects(origin, inverse_direction, entry.world):
                        yield entry
            else:
                pending.extend(node.children)


class QueryIndex:
    def __init__(self):
        self.entries = {}
        self.root = None
        self.dirty = True
        self.full_refresh = True
        self.transform_dirty = set()
        self.geometry_dirty = set()
        self.supported = False
        self.candidate_cache = {}

    def refresh(self, depsgraph):
        self.candidate_cache.clear()
        if not self.full_refresh and self.supported:
            changed = []
            for key in self.transform_dirty:
                entry = self.entries.get(key)
                obj = entry.object() if entry else None
                evaluated = obj.evaluated_get(depsgraph) if obj else None
                if evaluated is None or abs(evaluated.matrix_world.to_3x3().determinant()) < 1e-12:
                    self.full_refresh = True
                    break
                entry.refresh(evaluated)
                changed.append(entry)
            if not self.full_refresh:
                self.refit(changed)
                self.transform_dirty.clear()
                self.dirty = False
                return
        entries, changed = {}, []
        originals = {obj.as_pointer(): obj for obj in bpy.data.objects}
        supported = True
        for instance in depsgraph.object_instances:
            evaluated = instance.object
            if not instance.show_self or evaluated.type not in {"MESH", "VOLUME", "POINTCLOUD"}:
                continue
            obj = evaluated.original
            own_surface = (
                instance.is_instance
                and obj.type in {"CURVE", "SURFACE", "FONT", "META"}
                and instance.parent
                and instance.parent.original == obj
                and instance.matrix_world == obj.matrix_world
            )
            key = obj.as_pointer()
            if (
                evaluated.type != "MESH"
                or (instance.is_instance and not own_surface)
                or key in entries
                or key not in originals
            ):
                supported = False
                break
            if abs(instance.matrix_world.to_3x3().determinant()) < 1e-12:
                continue
            entry = self.entries.get(key)
            if entry is None:
                entry = Entry(instance, len(entries), originals[key])
            else:
                geometry = (
                    key in self.geometry_dirty or obj.data.as_pointer() in self.geometry_dirty
                )
                if geometry or entry.matrix != instance.matrix_world:
                    entry.refresh(instance, geometry=geometry)
                    changed.append(entry)
                entry.order = len(entries)
            entries[key] = entry
        if not supported:
            self.entries, self.root = {}, None
        elif (
            entries.keys() != self.entries.keys()
            or not self.root
            or len(changed) > len(entries) // 4
        ):
            self.entries = entries
            self.root = Node(list(entries.values())) if entries else None
        else:
            self.entries = entries
            self.refit(changed)
        self.supported = supported
        self.geometry_dirty.clear()
        self.transform_dirty.clear()
        self.full_refresh = False
        self.dirty = False

    def refit(self, changed):
        for leaf in {e.leaf() for e in changed}:
            leaf.refit()

    def query(self, view, origin, direction, distance):
        from .viewport import SurfaceHit, nearest_hit_conservative, ray_box

        window, _, _, space = view
        depsgraph = window.view_layer.depsgraph
        maximum_distance = distance
        key = tuple(origin), tuple(direction)
        candidates = self.candidate_cache.get(key)
        if candidates is None:
            inverse_direction = tuple(1 / d if abs(d) >= 1e-15 else None for d in direction)
            candidates = (
                sorted(self.root.candidates(key[0], inverse_direction), key=lambda e: e.order)
                if self.root
                else ()
            )
            if len(self.candidate_cache) >= 64:
                for old in list(self.candidate_cache)[:32]:
                    del self.candidate_cache[old]
            # Only geometric candidates survive a redraw. Re-read visibility,
            # display priority and the actual surface intersection every query.
            self.candidate_cache[key] = candidates
        closest = None
        # Query the whole positive ray: an in-front object behind the anchor
        # still has visual priority. Keep depsgraph order for coincident hits.
        for entry in candidates:
            obj = entry.object()
            if obj is None:
                # Rename/removal may precede a depsgraph notification. Re-read
                # this query instead of interpreting a stale identity as empty.
                self.dirty = self.full_refresh = True
                depsgraph.update()
                return nearest_hit_conservative(None, view, origin, direction, maximum_distance)
            if not obj.visible_get(view_layer=window.view_layer, viewport=space):
                continue
            local_origin = entry.inverse @ origin
            local_vector = entry.inverse.to_3x3() @ direction
            special = obj.show_in_front
            limit = float("inf") if special else distance
            travel = ray_box(local_origin, local_vector, entry.bounds, limit)
            if travel is None:
                continue
            reason = "wire_or_bounds_geometry" if obj.display_type in {"WIRE", "BOUNDS"} else None
            if reason:
                point, face = local_origin + local_vector * travel, -1
            else:
                length = local_vector.length
                local_limit = min(limit * length, 1e30)
                if obj.type == "MESH":
                    evaluated = obj.evaluated_get(depsgraph)
                    hit, point, _, face = evaluated.ray_cast(
                        local_origin,
                        local_vector / length,
                        distance=local_limit,
                        depsgraph=depsgraph,
                    )
                    if not hit:
                        continue
                else:
                    if entry.tree is None:
                        entry.tree = BVHTree.FromObject(obj, depsgraph)
                    point, _, face, _ = entry.tree.ray_cast(
                        local_origin, local_vector / length, local_limit
                    )
                    if point is None:
                        continue
            world = entry.matrix @ point
            travel = (world - origin).dot(direction)
            if travel < 0:
                continue
            if special:
                return SurfaceHit(
                    obj, point, face, world, travel, entry.is_instance, "in_front_geometry"
                )
            if travel <= distance:
                distance = travel
                closest = SurfaceHit(obj, point, face, world, travel, entry.is_instance, reason)
        return closest


def get_index(view):
    window = view[0]
    depsgraph = window.view_layer.depsgraph
    key = depsgraph.as_pointer(), window.view_layer.as_pointer()
    index = _indexes.get(key)
    if index is None:
        if len(_indexes) >= 4:
            _indexes.pop(next(iter(_indexes)))
        index = _indexes[key] = QueryIndex()
    if index.dirty:
        index.refresh(depsgraph)
    return index


def invalidate(depsgraph=None):
    if depsgraph is None:
        _indexes.clear()
        return
    dirty, transforms = set(), set()
    full_refresh = False
    for update in depsgraph.updates:
        item = update.id.original
        if update.is_updated_geometry:
            dirty.add(item.as_pointer())
            full_refresh = True
        elif isinstance(item, bpy.types.Object) and update.is_updated_transform:
            transforms.add(item.as_pointer())
        elif isinstance(item, (bpy.types.Object, bpy.types.Scene, bpy.types.Collection)):
            full_refresh = True
    if full_refresh or transforms:
        for (graph, _), index in _indexes.items():
            if graph == depsgraph.as_pointer():
                index.dirty = True
                index.full_refresh |= full_refresh
                index.geometry_dirty.update(dirty)
                index.transform_dirty.update(transforms)
