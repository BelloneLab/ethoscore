"""Exercise source-coordinate edge editing and polygon tracing through real Qt input."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from annotator_libs.arena_model import Arena
from annotator_libs.arena_ui import ArenaEditor


class ArenaEditingTests(unittest.TestCase):
    """Keep all previews synthetic and verify geometry rather than paint internals."""

    @classmethod
    def setUpClass(cls):
        """Reuse a single GUI application without touching application settings."""
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        """Open a preview whose source dimensions differ from its widget dimensions."""
        self.editor = ArenaEditor('synthetic.mp4', np.full((300, 400, 3), 180, np.uint8),
                                  [Arena('first', 'Arena 1', 60, 50, 200, 170)])
        self.editor.show()
        self.app.processEvents()
        self.preview = self.editor.preview

    def tearDown(self):
        """Close only the synthetic draft created by this test."""
        self.editor.close()
        self.app.processEvents()

    def point(self, x, y):
        """Map source coordinates through the actual zoom used by the preview."""
        return self.preview.mapFromScene(QPointF(x, y))

    def drag(self, start, end):
        """Send an ordinary mouse drag through the view's viewport."""
        QTest.mousePress(self.preview.viewport(), Qt.LeftButton, Qt.NoModifier, self.point(*start))
        QTest.mouseMove(self.preview.viewport(), self.point(*end))
        QTest.mouseRelease(self.preview.viewport(), Qt.LeftButton, Qt.NoModifier, self.point(*end))
        self.app.processEvents()

    def click(self, x, y):
        """Add one tracing vertex or select one arena."""
        QTest.mouseClick(self.preview.viewport(), Qt.LeftButton, Qt.NoModifier, self.point(x, y))

    def test_rectangle_edge_corner_and_move(self):
        """Resizing one edge leaves the opposite edge fixed and updates the table."""
        self.assertEqual(self.preview.mode, 'edit')
        self.drag((60, 130), (30, 130))
        arena = self.editor.arenas[0]
        self.assertAlmostEqual(arena.x, 30, delta=1)
        self.assertEqual(arena.x+arena.width, 260)
        self.assertEqual(self.editor.table.item(0, 1).text(), str(arena.x))
        self.drag((260, 220), (290, 240))
        arena = self.editor.arenas[0]
        self.assertAlmostEqual(arena.x+arena.width, 290, delta=1)
        self.assertAlmostEqual(arena.y+arena.height, 240, delta=1)
        width, height = arena.width, arena.height
        self.drag((150, 130), (170, 150))
        arena = self.editor.arenas[0]
        self.assertEqual((arena.width, arena.height), (width, height))
        self.assertAlmostEqual(arena.x, 50, delta=2)
        self.assertEqual(arena.id, 'first')

    def test_polygon_trace_undo_finish_and_vertex_edit(self):
        """Tracing supports undo and Enter, then exposes draggable vertices."""
        self.editor.set_edit_mode('polygon')
        self.click(40, 40)
        self.click(180, 40)
        self.click(230, 160)
        self.click(300, 250)
        QTest.keyClick(self.preview, Qt.Key_Backspace)
        self.assertEqual(len(self.preview._points), 3)
        self.click(60, 190)
        QTest.keyClick(self.preview, Qt.Key_Return)
        self.assertEqual(len(self.editor.arenas), 2)
        arena = self.editor.arenas[1]
        self.assertEqual(len(arena.polygon), 4)
        self.assertEqual(self.preview.mode, 'edit')
        self.assertFalse(self.editor.table.item(1, 1).flags() & Qt.ItemIsEditable)
        self.drag((40, 40), (20, 25))
        arena = self.editor.arenas[1]
        self.assertAlmostEqual(arena.polygon[0][0], 20, delta=1)
        self.assertAlmostEqual(arena.polygon[0][1], 25, delta=1)
        self.assertEqual(arena.x, arena.polygon[0][0])

    def test_polygon_close_first_and_escape_cancel(self):
        """Clicking the starting point closes; Escape discards only an unfinished trace."""
        self.editor.set_edit_mode('polygon')
        for point in ((40, 40), (180, 40), (160, 170), (40, 40)):
            self.click(*point)
        self.assertEqual(len(self.editor.arenas), 2)
        self.editor.set_edit_mode('polygon')
        self.click(90, 90)
        QTest.keyClick(self.preview, Qt.Key_Escape)
        self.assertEqual(len(self.preview._points), 0)
        self.assertEqual(len(self.editor.arenas), 2)
        self.assertTrue(self.editor.isVisible())

    def test_polygon_double_click_finishes_without_duplicate(self):
        """The first click adds the last vertex; its double-click completes once."""
        self.editor.set_edit_mode('polygon')
        for point in ((30, 30), (190, 30), (190, 180)):
            self.click(*point)
        QTest.mouseDClick(self.preview.viewport(), Qt.LeftButton, Qt.NoModifier, self.point(190, 180))
        self.assertEqual(len(self.editor.arenas), 2)
        self.assertEqual(len(self.editor.arenas[1].polygon), 3)

    def test_locked_geometry_and_bounded_moves(self):
        """Moves stay inside the image and exported geometry cannot be edited."""
        self.drag((150, 140), (390, 290))
        arena = self.editor.arenas[0]
        self.assertEqual(arena.x+arena.width, 400)
        self.assertEqual(arena.y+arena.height, 300)
        self.editor.geometry_locked = True
        self.preview.draw_enabled = False
        before = (arena.x, arena.y, arena.width, arena.height)
        self.drag((300, 200), (100, 100))
        self.assertEqual((arena.x, arena.y, arena.width, arena.height), before)
        self.editor.create_grid()
        self.assertEqual(len(self.editor.arenas), 1)

    def test_self_crossing_trace_retained_for_correction(self):
        """An invalid bow-tie cannot become an exported polygon."""
        self.editor.set_edit_mode('polygon')
        for point in ((30, 30), (180, 180), (180, 30), (30, 180)):
            self.click(*point)
        QTest.keyClick(self.preview, Qt.Key_Return)
        self.assertEqual(len(self.editor.arenas), 1)
        self.assertEqual(len(self.preview._points), 4)
        self.assertTrue(self.editor.hint.text())


if __name__ == '__main__':
    unittest.main()
