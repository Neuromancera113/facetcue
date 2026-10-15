"""Blender-independent surface math, validation and identifiers."""

import colorsys
import hashlib
import json
import math

SCHEMA_VERSION = 1
MAX_NOTE_LENGTH = 8000
# Existing enum ordinals are persisted by Blender. Append, never reorder.
STATUSES = ("OPEN", "IN_PROGRESS", "RESOLVED", "ARCHIVED", "MODIFIED", "CHANGES_REQUESTED")
# Status badges never replace a marker's identifying color. Extend this mapping
# when another state needs a badge; unlisted states have no badge.
STATUS_BADGES = {"MODIFIED": {"color": (0.12, 0.48, 1.0, 1.0), "label": "待审核"}}
PALETTE = (
    "FF4B4B",
    "20D9FF",
    "FFD93D",
    "B47BFF",
    "38E58C",
    "FF8B36",
    "FF63D8",
    "4B87FF",
    "C5F52A",
    "15D9BD",
    "F4B1FF",
    "FFE5AB",
)


class MarkError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def vector3(value):
    try:
        result = tuple(float(x) for x in value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise MarkError("INVALID_POSITION", "Expected three finite numbers") from exc
    if len(result) != 3 or not all(math.isfinite(x) for x in result):
        raise MarkError("INVALID_POSITION", "Expected three finite numbers")
    return result


def sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def interpolate(vertices, weights):
    return tuple(sum(vertices[j][i] * weights[j] for j in range(3)) for i in range(3))


def validate_anchor(anchor):
    """Validate persisted data before indexing RNA collections or doing math."""
    try:
        if not isinstance(anchor, dict):
            raise ValueError("Expected an anchor object")
        # JSON accepts NaN/Infinity by default in Python, including in unused
        # metadata. Never let those values invalidate the whole MCP response.
        json.dumps(anchor, allow_nan=False)
        indices = anchor["vertex_indices"]
        if not isinstance(indices, list) or len(indices) != 3 or len(set(indices)) != 3:
            raise ValueError("Expected three distinct vertex indices")
        for index in [*indices, anchor["triangle_index"], anchor["polygon_index"]]:
            if type(index) is not int or index < 0:
                raise ValueError("Expected nonnegative integer indices")
        weights = anchor["barycentric"]
        if not isinstance(weights, list) or len(weights) != 3:
            raise ValueError("Expected three barycentric weights")
        if any(
            type(w) not in (int, float) or not math.isfinite(w) or not 0 <= w <= 1 for w in weights
        ):
            raise ValueError("Expected finite weights in [0, 1]")
        if abs(sum(weights) - 1) > 1e-6:
            raise ValueError("Barycentric weights must sum to one")
        signature = anchor["topology_fingerprint"]
        if (
            not isinstance(signature, str)
            or len(signature) != 64
            or any(c not in "0123456789abcdef" for c in signature)
        ):
            raise ValueError("Invalid topology fingerprint")
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise MarkError("CORRUPT_ANNOTATION", str(exc)) from exc
    return anchor


def barycentric(point, a, b, c):
    point, a, b, c = map(vector3, (point, a, b, c))
    u, v, w = sub(b, a), sub(c, a), sub(point, a)
    uu, uv, vv, wu, wv = dot(u, u), dot(u, v), dot(v, v), dot(w, u), dot(w, v)
    determinant = uu * vv - uv * uv
    if uu == 0 or vv == 0 or determinant <= 1e-12 * uu * vv:
        raise MarkError("DEGENERATE_TRIANGLE", "Triangle has insufficient area")
    wb = (vv * wu - uv * wv) / determinant
    wc = (uu * wv - uv * wu) / determinant
    weights = (1 - wb - wc, wb, wc)
    projected = interpolate((a, b, c), weights)
    distance = math.sqrt(dot(sub(point, projected), sub(point, projected)))
    tolerance = max(1e-7, math.sqrt(max(uu, vv)) * 1e-6)
    if distance > tolerance or min(weights) < -1e-6 or max(weights) > 1 + 1e-6:
        raise MarkError("POINT_OUTSIDE_TRIANGLE", "Position must lie on the chosen triangle")
    clamped = tuple(max(0.0, min(1.0, x)) for x in weights)
    return tuple(x / sum(clamped) for x in clamped)


def topology_fingerprint(vertex_count, edges, polygons, triangles):
    # Coordinates intentionally excluded: the anchor follows vertex deformation.
    data = [vertex_count, list(edges), list(polygons), list(triangles)]
    return hashlib.sha256(json.dumps(data, separators=(",", ":")).encode()).hexdigest()


def color_for_number(number):
    if number < 1:
        raise ValueError("Marker numbers start at one")
    if number <= len(PALETTE):
        color = PALETTE[number - 1]
        return tuple(int(color[i : i + 2], 16) / 255 for i in (0, 2, 4)) + (1.0,)
    return colorsys.hsv_to_rgb(((number - 1) * 0.61803398875) % 1, 0.62, 1.0) + (1.0,)


def choose_marker_color(number, used_colors):
    """Choose an unused color with maximum separation from current marker colors.

    Quantized RGB comparison avoids collisions after Blender stores float values.
    Existing marks never change color when more marks are added or reviewed.
    """
    used = {tuple(round(channel * 255) for channel in color[:3]) for color in used_colors}
    if not used:
        return color_for_number(number)
    candidates = [color_for_number(i) for i in range(1, len(PALETTE) + 1)]
    candidates += [
        colorsys.hsv_to_rgb(hue / 72, saturation, value) + (1.0,)
        for hue in range(72)
        for saturation in (0.55, 0.8, 1.0)
        for value in (0.8, 1.0)
    ]
    candidates = [c for c in candidates if tuple(round(v * 255) for v in c[:3]) not in used]
    if not candidates:
        index = number
        while True:
            color = color_for_number(index)
            if tuple(round(v * 255) for v in color[:3]) not in used:
                return color
            index += 1
    return max(
        candidates,
        key=lambda color: min(
            sum((color[i] * 255 - other[i]) ** 2 for i in range(3)) for other in used
        ),
    )


def validate_note(note):
    if not isinstance(note, str) or len(note) > MAX_NOTE_LENGTH:
        raise MarkError(
            "INVALID_NOTE", f"Note must be a string of at most {MAX_NOTE_LENGTH} characters"
        )
    return note
