import unittest

from blender_agent_marks.core import (
    MarkError,
    barycentric,
    choose_marker_color,
    color_for_number,
    interpolate,
    topology_fingerprint,
    validate_note,
)


class AnchorTests(unittest.TestCase):
    def test_barycentric_round_trip(self):
        vertices = ((0, 0, 0), (2, 0, 0), (0, 4, 0))
        weights = barycentric((0.5, 1, 0), *vertices)
        self.assertEqual(weights, (0.5, 0.25, 0.25))
        self.assertEqual(interpolate(vertices, weights), (0.5, 1, 0))

    def test_off_plane_outside_nonfinite_rejected(self):
        for point in ((0, 0, 1), (2, 2, 0), (float("nan"), 0, 0)):
            with self.assertRaises(MarkError):
                barycentric(point, (0, 0, 0), (1, 0, 0), (0, 1, 0))

    def test_degenerate_triangle_rejected(self):
        with self.assertRaises(MarkError):
            barycentric((0, 0, 0), (0, 0, 0), (1, 0, 0), (2, 0, 0))

    def test_connectivity_changes_with_equal_counts(self):
        first = topology_fingerprint(4, [], [[0, 1, 2], [1, 2, 3]], [])
        second = topology_fingerprint(4, [], [[0, 2, 1], [1, 2, 3]], [])
        self.assertNotEqual(first, second)

    def test_colors_unique_for_first_hundred(self):
        colors = [color_for_number(i) for i in range(1, 101)]
        self.assertEqual(len(set(colors)), 100)
        self.assertTrue(all(0 <= x <= 1 for c in colors for x in c))

    def test_note_limit(self):
        self.assertEqual(validate_note("修改此处，保留圆角"), "修改此处，保留圆角")
        self.assertEqual(validate_note("注" * 8000), "注" * 8000)
        with self.assertRaises(MarkError):
            validate_note("a" * 8001)

    def test_allocated_colors_do_not_repeat_and_preserve_existing(self):
        colors = [color_for_number(1)]
        original = colors[0]
        for _ in range(30):
            colors.append(choose_marker_color(1, colors))
        quantized = {tuple(round(channel * 255) for channel in color[:3]) for color in colors}
        self.assertEqual(len(quantized), len(colors))
        self.assertEqual(colors[0], original)


if __name__ == "__main__":
    unittest.main()
