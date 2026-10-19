"""Exercise arena isolation through the real Qt editor using synthetic videos.

Tests run offscreen and redirect every QSettings store to a temporary directory.
They never close or change an existing user session or open real recordings.
"""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np
import pandas as pd
from PySide6.QtCore import QSettings, Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

import ethoscore
from annotator_libs.arena_export import export_arenas, ffmpeg_executable
from annotator_libs.arena_model import Arena, ArenaProject, default_project_dir
from annotator_libs.arena_ui import ArenaEditor


class ArenaWorkflowTests(unittest.TestCase):
    """Verify real crop selection, isolated CSVs, progress, and manual drawing."""

    @classmethod
    def setUpClass(cls):
        """Keep a single QApplication alive for all widgets in this module."""
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        """Create two distinct crop videos and private application settings."""
        self.temporary = tempfile.TemporaryDirectory(prefix="ethoscore-workflow-test-")
        self.root = Path(self.temporary.name)
        self.source = self.root / "two_arenas.mkv"
        frames = []
        for index in range(18):
            frame = np.zeros((72, 96, 3), np.uint8)
            frame[:, :48] = (30, 90, 160)
            frame[:, 48:] = (150, 60, 25)
            frame[index * 3:index * 3 + 3] = (index * 10, 220, 220)
            frames.append(frame)
        result = subprocess.run([
            ffmpeg_executable(), "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
            "-s", "96x72", "-r", "30", "-i", "pipe:0", "-c:v", "ffv1", str(self.source),
        ], input=b"".join(frame.tobytes() for frame in frames), capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.arenas = [Arena("left", "Arena 1", 0, 0, 48, 72), Arena("right", "Arena 2", 48, 0, 48, 72)]
        self.project_dir = default_project_dir(self.source)
        export_arenas(self.source, self.arenas, self.project_dir, lossless=True)
        self.settings_patch = patch.object(ethoscore, "QSettings", self.private_settings)
        self.settings_patch.start()
        self.window = ethoscore.VideoAnnotator()
        self.window.auto_save_timer.stop()
        self.window.gamepad_timer.stop()
        self.window.show_statistics_popup = False
        self.window.resize(1240, 900)

    def private_settings(self, organization, application):
        """Replace registry-backed settings with disposable INI files."""
        return QSettings(str(self.root / f"{organization}_{application}.ini"), QSettings.IniFormat)

    def tearDown(self):
        """Save only synthetic annotations, then stop workers before deleting files."""
        self.window.close()
        self.app.processEvents()
        self.settings_patch.stop()
        self.temporary.cleanup()

    def test_switch_isolates_annotations_and_restores_frame(self):
        """Each selected crop fills the view and owns its labels, undo, and frame."""
        self.assertTrue(self.window.load_video_by_path(str(self.source)))
        self.assertEqual(self.window.active_arena_id, "left")
        self.assertEqual(self.window.video_path, str(self.arenas[0].video_path(self.project_dir)))
        self.assertEqual(self.window.video_player.total_frames, 18)
        self.assertEqual(self.window.video_player.original_pixmap.width(), 48)
        self.window.video_player.goto_frame(3)
        self.window.push_undo_state()
        self.window.annotations[3] = ["rearing"]
        self.assertEqual(self.window.active_arena().status, "ongoing")
        self.assertTrue(self.window.switch_arena("right"))
        self.assertEqual(self.window.annotations, {})
        self.assertEqual(self.window.undo_stack, [])
        self.assertFalse(self.window.video_player.range_labeling_active)
        left_csv = pd.read_csv(self.arenas[0].annotations_path(self.project_dir))
        self.assertEqual(len(left_csv), 18)
        self.assertEqual(left_csv.loc[3, "Frames"], 4)
        self.assertEqual(left_csv.loc[3, "rearing"], 1)
        self.window.video_player.goto_frame(8)
        self.window.push_undo_state()
        self.window.annotations[8] = ["passive"]
        self.assertTrue(self.window.switch_arena("left"))
        self.assertEqual(self.window.annotations, {3: ["rearing"]})
        self.assertEqual(self.window.video_player.current_frame, 3)
        self.assertEqual(self.window.last_video_path, str(self.source))
        right_csv = pd.read_csv(self.arenas[1].annotations_path(self.project_dir))
        self.assertEqual(right_csv.loc[8, "passive"], 1)
        self.assertEqual(right_csv["rearing"].sum(), 0)
        self.assertFalse(self.source.with_suffix(".csv").exists())

    def test_completion_persists_and_edit_reopens(self):
        """Explicit completion works even without labels; a later edit reopens work."""
        self.window.load_video_by_path(str(self.source))
        status = self.window.arena_status_selector
        status.setCurrentIndex(status.findData("completed"))
        self.assertEqual(ArenaProject.load(self.project_dir).arenas[0].status, "completed")
        self.window.push_undo_state()
        self.assertEqual(self.window.active_arena().status, "ongoing")
        self.window.video_player.range_labeling_active = {"rearing": True}
        self.window.video_player.range_labeling_start = {"rearing": 1}
        self.window.video_player.current_frame = 5
        self.window.video_player.include_last_frame_in_range = True
        self.window.switch_arena("right")
        self.assertFalse(self.window.video_player.range_labeling_active)
        self.assertEqual(self.window.annotations, {})
        left_csv = pd.read_csv(self.arenas[0].annotations_path(self.project_dir))
        self.assertEqual(left_csv["rearing"].sum(), 5)
        self.window.discover_arena_project(str(self.arenas[0].video_path(self.project_dir)))
        self.assertEqual(self.window.active_arena_id, "left")

    def test_failed_save_prevents_arena_switch(self):
        """A full disk or permission failure must not discard the current labels."""
        self.window.load_video_by_path(str(self.source))
        self.window.annotations[2] = ["rearing"]
        with patch.object(ethoscore, "save_annotations_to_csv", side_effect=OSError("disk full")), \
             patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok):
            self.assertFalse(self.window.switch_arena("right"))
        self.assertEqual(self.window.active_arena_id, "left")
        self.assertEqual(self.window.annotations[2], ["rearing"])

    def test_manual_drawing_and_name_validation(self):
        """Dragging over a scaled preview creates valid source-pixel coordinates."""
        capture = cv2.VideoCapture(str(self.source))
        ok, frame = capture.read()
        capture.release()
        self.assertTrue(ok)
        editor = ArenaEditor(self.source, frame)
        editor.show()
        self.app.processEvents()
        preview = editor.preview
        start = preview.mapFromScene(8, 10)
        end = preview.mapFromScene(40, 60)
        QTest.mousePress(preview.viewport(), Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(preview.viewport(), end)
        QTest.mouseRelease(preview.viewport(), Qt.LeftButton, Qt.NoModifier, end)
        self.assertEqual(len(editor.arenas), 1)
        arena = editor.arenas[0]
        self.assertLessEqual(abs(arena.x - 8), 1)
        self.assertLessEqual(abs(arena.y - 10), 1)
        self.assertGreater(arena.height, 45)
        editor.add_rectangle(50, 2, 30, 60)
        editor.table.item(1, 0).setText(editor.arenas[0].label)
        self.assertFalse(editor.apply_button.isEnabled())
        editor.table.item(1, 0).setText("Mouse B")
        self.assertTrue(editor.apply_button.isEnabled())
        editor.reject()

    def test_invalid_csv_does_not_replace_current_session(self):
        """Malformed target annotations must never be treated as an empty arena."""
        self.window.load_video_by_path(str(self.source))
        self.window.annotations[4] = ['passive']
        bad_csv = self.arenas[1].annotations_path(self.project_dir)
        bad_csv.write_text('Frames,passive\n1,1\n3,0\n', encoding='utf-8')
        original = bad_csv.read_bytes()
        with patch.object(QMessageBox, 'warning', return_value=QMessageBox.Ok):
            self.assertFalse(self.window.switch_arena('right'))
        self.assertEqual(self.window.active_arena_id, 'left')
        self.assertEqual(self.window.video_path, str(self.arenas[0].video_path(self.project_dir)))
        self.assertEqual(self.window.annotations, {4: ['passive']})
        self.assertEqual(bad_csv.read_bytes(), original)

    def test_unreadable_crop_preserves_current_session_and_csv(self):
        """A broken target video must not clear the old editor or its saved data."""
        self.window.load_video_by_path(str(self.source))
        self.window.annotations[4] = ['passive']
        target = self.arenas[1].video_path(self.project_dir)
        target.write_bytes(b'not a valid movie')
        def autosave_during_modal(*args):
            """Reproduce an autosave timer inside the decoder error's modal loop."""
            self.window.auto_save_annotations()
            frame = pd.read_csv(self.arenas[0].annotations_path(self.project_dir))
            self.assertEqual(frame.loc[4, 'passive'], 1)
            return QMessageBox.Ok

        with patch.object(QMessageBox, 'warning', side_effect=autosave_during_modal):
            self.assertFalse(self.window.switch_arena('right'))
        self.assertEqual(self.window.active_arena_id, 'left')
        self.assertEqual(self.window.video_path, str(self.arenas[0].video_path(self.project_dir)))
        self.assertEqual(self.window.annotations, {4: ['passive']})
        self.assertTrue(self.window.video_player.video_capture.isOpened())
        self.window.save_annotations()
        frame = pd.read_csv(self.arenas[0].annotations_path(self.project_dir))
        self.assertEqual(frame.loc[4, 'passive'], 1)

    def test_failed_full_video_load_keeps_arena_and_blocks_modal_autosave(self):
        """A failed normal file-open retains arena metadata and every saved label."""
        self.window.load_video_by_path(str(self.source))
        self.window.annotations[4] = ['passive']
        broken = self.root / 'broken.mp4'
        broken.write_bytes(b'not a valid video')

        def autosave_during_modal(*args):
            """Saving from the error dialog must leave the prior CSV untouched."""
            self.window.auto_save_annotations()
            frame = pd.read_csv(self.arenas[0].annotations_path(self.project_dir))
            self.assertEqual(frame.loc[4, 'passive'], 1)
            return QMessageBox.Ok

        with patch.object(QMessageBox, 'warning', side_effect=autosave_during_modal):
            self.assertFalse(self.window.load_video_by_path(str(broken)))
        self.assertEqual(self.window.active_arena_id, 'left')
        self.assertEqual(self.window.annotations, {4: ['passive']})
        self.assertTrue(self.window.video_player.video_capture.isOpened())


if __name__ == "__main__":
    unittest.main()
