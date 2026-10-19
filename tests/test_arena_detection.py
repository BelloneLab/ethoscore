"""Ground-truth synthetic geometry checks for contrast-adaptive arena proposals.

Run ``python -m unittest discover -s tests -p test_arena_detection.py -v``.
All images are generated in memory. User recordings are never modified.
"""

import unittest

import cv2
import numpy as np

from annotator_libs.arena_model import detect_arenas


# Explicit source-space, half-open geometry shared with the benchmark script.
WIDTH, HEIGHT = 640, 480
FLOOR = (80, 40, 580, 440)
DIVIDER_X, DIVIDER_Y = 320, 240
BOUNDARY_TOLERANCE = 6


def synthetic_scene(inverted=False, border="all", animals=False, gradient=False):
    """Create four known arenas, optionally reversing floor/border contrast.

    Dividers span the entire source, like physical walls visible over a surround.
    The expected crops share the divider centre and omit exterior padding.
    """
    left, top, right, bottom = FLOOR if border == "all" else (0, 0, WIDTH, HEIGHT)
    if border == "left":
        left = FLOOR[0]
    frame = np.full((HEIGHT, WIDTH), 25, np.uint8)
    frame[top:bottom, left:right] = 205
    if gradient:
        illumination = np.linspace(115, 220, WIDTH).astype(np.uint8)
        frame[:] = illumination
    frame[:, DIVIDER_X - 2:DIVIDER_X + 2] = 25
    frame[DIVIDER_Y - 2:DIVIDER_Y + 2, :] = 25
    if animals:
        for center in ((180, 140), (465, 145), (200, 340), (470, 350)):
            cv2.ellipse(frame, center, (26, 13), 25, 0, 360, 25, -1)
    if inverted:
        frame = 255 - frame
    expected = [(left, top, DIVIDER_X, DIVIDER_Y),
                (DIVIDER_X, top, right, DIVIDER_Y),
                (left, DIVIDER_Y, DIVIDER_X, bottom),
                (DIVIDER_X, DIVIDER_Y, right, bottom)]
    return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR), expected


class ContrastAdaptiveDetectionTests(unittest.TestCase):
    """Check boundary accuracy as well as proposal counts and polarity."""

    def assert_geometry(self, image, expected):
        """Compare every edge against independently specified floor geometry."""
        arenas = detect_arenas(image)
        self.assertEqual(len(arenas), len(expected))
        for arena, truth in zip(arenas, expected):
            actual = (arena.x, arena.y, arena.x + arena.width, arena.y + arena.height)
            for observed, target in zip(actual, truth):
                self.assertLessEqual(abs(observed - target), BOUNDARY_TOLERANCE,
                                     f"{arena.label}: {actual} versus {truth}")

    def test_exterior_trim_both_contrast_polarities(self):
        """Bright floors trim dark padding; dark floors trim bright padding."""
        for inverted in (False, True):
            with self.subTest(inverted=inverted):
                self.assert_geometry(*synthetic_scene(inverted=inverted))

    def test_single_side_border(self):
        """A border on one side must not trim the three unpadded sides."""
        for inverted in (False, True):
            with self.subTest(inverted=inverted):
                self.assert_geometry(*synthetic_scene(inverted=inverted, border="left"))

    def test_multitone_surround_reaches_floor_boundary(self):
        """A gray ledge inside black padding is still outside the arena floor."""
        frame, expected = synthetic_scene()
        # Preserve the long dividing walls while adding an intermediate ledge.
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        ledge = np.zeros(gray.shape, dtype=bool)
        ledge[20:460, 40:610] = True
        ledge[40:440, 80:580] = False
        ledge[:, DIVIDER_X - 2:DIVIDER_X + 2] = False
        ledge[DIVIDER_Y - 2:DIVIDER_Y + 2, :] = False
        gray[ledge] = 90
        for inverted in (False, True):
            with self.subTest(inverted=inverted):
                image = 255 - gray if inverted else gray
                self.assert_geometry(cv2.cvtColor(image, cv2.COLOR_GRAY2BGR), expected)

    def test_no_border_preserves_frame_extent(self):
        """Full-frame arenas retain their edges for either floor polarity."""
        for inverted in (False, True):
            with self.subTest(inverted=inverted):
                self.assert_geometry(*synthetic_scene(inverted=inverted, border="none"))

    def test_animals_do_not_become_boundaries(self):
        """Small contrasting animals must not shrink valid arena floors."""
        for inverted in (False, True):
            with self.subTest(inverted=inverted):
                self.assert_geometry(*synthetic_scene(inverted=inverted, animals=True))

    def test_smooth_illumination_is_not_padding(self):
        """Gradual illumination changes do not justify cutting off the floor."""
        self.assert_geometry(*synthetic_scene(border="none", gradient=True))

    def test_blank_or_animal_only_has_no_supported_grid(self):
        """No sustained dividing wall means no automatic grid proposal."""
        frame = np.full((HEIGHT, WIDTH, 3), 180, np.uint8)
        self.assertEqual(detect_arenas(frame), [])
        cv2.ellipse(frame, (240, 180), (35, 18), 30, 0, 360, (20, 20, 20), -1)
        self.assertEqual(detect_arenas(frame), [])


if __name__ == "__main__":
    unittest.main()
