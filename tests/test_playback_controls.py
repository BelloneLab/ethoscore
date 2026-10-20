"""Behavioral transport checks, including annotation-safe slow decoding."""

import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import unittest
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QApplication, QDialog, QWidget
from annotator_libs.playback_controls import PlaybackControls


class FakePlayer(QWidget):
    """Record actual requested frames without relying on decoder timings."""
    frame_changed = Signal(int)
    transport_stopping = Signal()
    video_loaded = Signal()

    def __init__(self):
        super().__init__()
        self.current_frame = 0
        self.total_frames = 1000
        self.frame_rate = 30
        self.removing_mode = False
        self.active_labels = {}
        self.visited = []

    def goto_frame(self, frame):
        """Record transitions and emit the same update as the video widget."""
        self.current_frame = frame
        self.visited.append(frame)
        self.frame_changed.emit(frame)


class PlaybackTests(unittest.TestCase):
    """Test transport semantics with a deterministic monotonic clock."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.player = FakePlayer()
        self.settled = []
        self.controls = PlaybackControls(self.player, lambda: self.settled.append(self.player.current_frame))
        self.now = 0.0
        self.controls._clock = lambda: self.now

    def tearDown(self):
        self.controls.pause()
        self.app.removeEventFilter(self.controls)
        self.controls.deleteLater()
        self.player.deleteLater()
        self.app.processEvents()

    def test_elapsed_time_catches_up_and_stops_at_end(self):
        self.controls.toggle()
        self.now = 2.0
        self.controls._tick()
        self.assertEqual(self.player.current_frame, 60)
        self.now = 100.0
        self.controls._tick()
        self.assertEqual(self.player.current_frame, 999)
        self.assertFalse(self.controls.timer.isActive())

    def test_annotation_never_skips_frames_when_decoder_falls_behind(self):
        self.player.active_labels = {'groom': True}
        self.controls.toggle()
        for value in (2.0, 4.0, 8.0):
            self.now = value
            self.controls._tick()
        self.assertEqual(self.player.visited, [1, 2, 3])

    def test_scrub_coalesces_and_release_commits_exact_final_frame(self):
        self.controls._begin_seek()
        for value in (20, 400, 827):
            self.controls.slider.setValue(value)
        self.assertEqual(self.player.visited, [])
        self.controls._finish_seek()
        self.assertEqual(self.player.visited, [827])
        self.assertEqual(self.settled, [0])
        self.assertEqual(self.controls.frame.value(), 828)

    def test_transition_discards_pending_seek_and_updates_range(self):
        self.controls._begin_seek()
        self.controls._queue_seek(827)
        self.player.transport_stopping.emit()
        self.controls._flush_seek()
        self.assertEqual(self.player.visited, [])
        self.player.total_frames = 12
        self.player.video_loaded.emit()
        self.assertEqual(self.controls.slider.maximum(), 11)
        self.controls.seek(500)
        self.assertEqual(self.player.current_frame, 11)

    def test_modal_dialog_pauses_playback(self):
        self.controls.toggle()
        dialog = QDialog()
        dialog.setModal(True)
        dialog.show()
        self.assertFalse(self.controls.timer.isActive())
        dialog.close()

    def test_manual_frame_entry_settles_before_jump(self):
        self.controls.frame.setValue(600)
        self.assertEqual(self.settled, [0])
        self.assertEqual(self.player.current_frame, 599)
        self.assertEqual(self.controls.slider.value(), 599)


if __name__ == '__main__':
    unittest.main()
