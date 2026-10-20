"""Exercise the export dialog with disposable footage and annotation snapshots."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest

import cv2
import numpy as np
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow

from annotator_libs.bout_grid_ui import BoutGridDialog


class BoutGridDialogTests(unittest.TestCase):
    """Check source scope, unsaved snapshots, and a real background export."""

    def setUp(self):
        """Generate a short source and a minimal owner without user preferences."""
        self.app = QApplication.instance() or QApplication([])
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.avi"
        writer = cv2.VideoWriter(str(self.source), cv2.VideoWriter_fourcc(*"MJPG"), 12, (64, 48))
        for index in range(12):
            writer.write(np.full((48, 64, 3), 30 + index * 10, np.uint8))
        writer.release()
        self.window = QMainWindow()
        self.window.video_path = str(self.source)
        self.window.annotations = {0: ["walk"], 1: ["walk"], 6: ["walk"]}
        self.window.behavior_buttons = SimpleNamespace(behaviors=["walk", "rear"])
        self.window.active_arena_id = "a"
        self.window.active_arena = lambda: SimpleNamespace(label="Arena A")
        self.window.arena_project_dir = self.root
        self.window.arena_project = SimpleNamespace(source_path=str(self.source), arenas=[
            SimpleNamespace(id="a", label="Arena A", video_path=lambda _: self.source),
            SimpleNamespace(id="b", label="Arena B", video_path=lambda _: self.source)])
        self.window.read_arena_annotations = lambda _: ({3: ["rear"]}, ["rear"])
        self.dialog = BoutGridDialog(self.window)

    def tearDown(self):
        """Wait for cancellation before releasing only disposable test outputs."""
        if self.dialog.worker:
            self.dialog.worker.requestInterruption()
            self.dialog.worker.wait(15000)
            self.app.processEvents()
        self.dialog.close()
        self.window.close()
        self.temporary.cleanup()

    def test_scope_and_snapshot(self):
        """Active unsaved labels and saved other-arena labels remain distinct."""
        self.assertIn("2 bouts", self.dialog.summary.text())
        self.window.annotations[2] = ["rear"]
        self.assertNotIn(2, self.dialog.sources[0].annotations)
        self.dialog.scope.setCurrentIndex(1)
        self.dialog.behavior.setCurrentText("rear")
        self.assertIn("2 bouts", self.dialog.summary.text())
        self.assertEqual(len(self.dialog.sources), 2)

    def test_worker_export_and_existing_folder(self):
        """The Qt worker publishes a real movie and prevents accidental reuse."""
        self.dialog.rows.setValue(1)
        self.dialog.columns.setValue(2)
        self.dialog.seconds.setValue(1)
        self.dialog.start_export()
        deadline = time.monotonic() + 60
        while self.dialog.worker and time.monotonic() < deadline:
            QTest.qWait(25)
        self.assertIsNone(self.dialog.worker)
        self.assertTrue(self.dialog.open_folder.isEnabled(), self.dialog.summary.text())
        self.assertTrue((self.dialog.output / "bout_grid.mp4").is_file())
        self.assertTrue((self.dialog.output / "bouts.csv").is_file())
        self.dialog.start_export()
        self.assertIn("already exist", self.dialog.summary.text())
        self.assertIsNone(self.dialog.worker)


if __name__ == "__main__":
    unittest.main()
